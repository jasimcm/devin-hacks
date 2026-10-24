"""Telegram bot (python-telegram-bot v21), run with long polling inside the FastAPI process.
Long polling means the Mac asks Telegram for new messages: no webhook or tunnel needed.

Shopkeeper: sends a voice note (or types the items) to the bot
  -> Gemini transcribes and picks items -> prices from inventory.json
  -> bill saved, printed on the Mac, shown on the counter screen -> bot replies with summary + PDF.
Customer: scans https://t.me/<bot>?start=<BillID> on the counter screen and taps Start
  -> Telegram sends "/start EB-0042" -> bot replies with summary + PDF.
Bots cannot message people who never started a chat, which is why we use this deep link.

If the shopkeeper says a phone number and whatsapp-sender/ is linked, the bill is sent to that
WhatsApp automatically after a countdown (AUTO_SEND_SECONDS) unless the shopkeeper cancels.
Otherwise the bot gives a "Send on WhatsApp" button that opens the shopkeeper's WhatsApp.
"""
import asyncio
import logging
import math
import re
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.error import BadRequest, NetworkError
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters,
)

import parser as bill_parser
import pdf_gen
import printer
import store
import wa_sender

log = logging.getLogger("easybill.bot")

WELCOME = (
    "നമസ്കാരം! 🙏 ഞാൻ കിങ്കരൻ, {shop}.\n"
    "മുതലാളി പറഞ്ഞാ മതി, ബാക്കി കിങ്കരൻ നോക്കിക്കോളും 💪\n\n"
    "🧾 Customers: scan the Telegram QR at the shop counter to get your bill here.\n"
    "കടയിലെ QR കോഡ് സ്കാൻ ചെയ്താൽ നിങ്ങളുടെ ബിൽ ഇവിടെ ലഭിക്കും.\n\n"
    "🎙️ Shopkeeper: send the items as a voice note or text, e.g. \"രണ്ട് കിലോ അരി, ഒരു സോപ്പ്\"."
)
TRY_AGAIN = (
    "ക്ഷമിക്കണം, ഒരു പിശക് സംഭവിച്ചു. ഒന്നുകൂടി അയക്കാമോ?\n"
    "Sorry, something went wrong (slow network?). Please send it again."
)
BAD_NUMBER = (
    "📲 I heard \"{heard}\", which is not a 10-digit mobile number.\n"
    "നമ്പർ വ്യക്തമായില്ല. ദയവായി നമ്പർ ടൈപ്പ് ചെയ്യൂ. Please type the number."
)
NOT_UNDERSTOOD = (
    "ക്ഷമിക്കണം, സാധനങ്ങൾ മനസ്സിലായില്ല. വീണ്ടും പറയാമോ?\n"
    "Sorry, I couldn't find any items in that. Please try again.\n\nI heard: \"{heard}\""
)


async def send_bill(message, bill):
    await message.reply_text(store.bill_summary(bill))
    await message.reply_document(
        document=pdf_gen.build_pdf(bill),
        filename=f"EasyBill_{bill['bill_id']}.pdf",
        caption=f"{store.SHOP_NAME} · {bill['bill_id']}",
    )


# ---------------------------------------------------------------- Customer

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(WELCOME.format(shop=store.SHOP_NAME))
        return

    bill_id = context.args[0].upper()
    bill = store.get_bill(bill_id)
    if bill is None:
        await update.message.reply_text(
            f"ക്ഷമിക്കണം, {bill_id} എന്ന ബിൽ കണ്ടെത്താനായില്ല.\n"
            f"Sorry, we could not find bill {bill_id}. Please ask the shopkeeper to show the QR again."
        )
        return

    await send_bill(update.message, bill)
    store.mark_delivered(bill_id, "telegram")
    log.info("Sent %s to chat %s", bill_id, update.effective_chat.id)


# ---------------------------------------------------------------- Shopkeeper

async def voice_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    audio = update.message.voice or update.message.audio
    await update.message.reply_text("🎙️ കേൾക്കുന്നു… Listening…")
    await update.message.chat.send_action(ChatAction.TYPING)
    data = await download_voice(audio)
    try:
        # Gemini is a slow, blocking call: run it in a thread so the web app keeps responding.
        transcript, items, phone, unknown = await asyncio.to_thread(
            bill_parser.parse_audio, data, audio.mime_type or "audio/ogg"
        )
    except Exception as error:
        log.error("Voice note failed: %s", error)
        await update.message.reply_text(
            "ക്ഷമിക്കണം, വോയ്സ് മനസ്സിലാക്കാനായില്ല. ടൈപ്പ് ചെയ്ത് അയക്കാമോ?\n"
            "Sorry, I couldn't process the voice note. Please type the items instead."
        )
        return
    if not items and not phone and bill_parser.is_cancel(transcript):
        await cancel_by_message(update, context)
        return
    await make_bill(update, context, transcript, items, phone, unknown, "🎙️")


async def download_voice(audio, attempts=2):
    """Download a voice note from Telegram, trying once more if the network is slow."""
    for attempt in range(1, attempts + 1):
        try:
            file = await audio.get_file()
            return bytes(await file.download_as_bytearray())
        except NetworkError as error:  # TimedOut is a NetworkError too
            log.warning("Voice note download failed (attempt %d): %s", attempt, error)
            if attempt == attempts:
                raise


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if bill_parser.is_greeting(text):  # don't spend a Gemini request on "hi"
        await update.message.reply_text(WELCOME.format(shop=store.SHOP_NAME))
        return
    if bill_parser.is_cancel(text):
        await cancel_by_message(update, context)
        return
    text_without_phone, phone = bill_parser.split_phone(text)
    if re.search(r"[^\W\d_]", text_without_phone):  # has letters, so maybe items
        items, _, unknown = await asyncio.to_thread(bill_parser.parse, text_without_phone)
    else:  # only a (phone) number: no need to ask Gemini
        items, unknown = [], []
    await make_bill(update, context, text, items, phone, unknown, "📝")


async def make_bill(update, context, transcript, items, phone, unknown, icon):
    not_in_list = ""
    if unknown:
        not_in_list = "\n\n⚠️ വിലവിവരപ്പട്ടികയിൽ ഇല്ല / Not in price list (not billed):\n• " + "\n• ".join(unknown)
    if not items:
        digits = re.sub(r"\D", "", transcript)
        if phone:  # just a number: it belongs to the last bill
            await attach_phone(update, context, phone)
        elif len(digits) >= 6:  # sounded like a number, but not a valid 10-digit mobile
            await update.message.reply_text(BAD_NUMBER.format(heard=digits))
        else:
            await update.message.reply_text(NOT_UNDERSTOOD.format(heard=transcript) + not_in_list)
        return
    lines, total = store.price_items(items)
    bill = store.create_bill(lines, total, channel="telegram", transcript=transcript, customer_phone=phone)
    context.chat_data["last_bill_id"] = bill["bill_id"]
    await asyncio.to_thread(printer.print_bill, bill)
    log.info("Telegram bill %s for ₹%.2f (customer %s)", bill["bill_id"], total, phone or "-")

    message = update.message
    await message.reply_text(f"{icon} \"{transcript}\"\n\n{store.bill_summary(bill)}{not_in_list}")
    await message.reply_document(
        document=pdf_gen.build_pdf(bill),
        filename=f"EasyBill_{bill['bill_id']}.pdf",
        caption=f"🖨️ Printed · {bill['bill_id']}",
    )
    await deliver_to_customer(message, context, bill)


async def attach_phone(update, context, phone):
    """A message with only a phone number: add it to this chat's last bill (or replace the old number)."""
    bill_id = context.chat_data.get("last_bill_id")
    if bill_id is None:  # e.g. after a server restart: use the newest Telegram bill
        latest = store.latest_bill()
        bill_id = latest["bill_id"] if latest and latest["channel"] == "telegram" else None
    if bill_id is None:
        await update.message.reply_text(
            f"📲 {store.format_phone(phone)}: ആദ്യം സാധനങ്ങൾ പറയൂ. Send the items first, then the number."
        )
        return
    bill = store.set_customer_phone(bill_id, phone)
    log.info("Customer %s added to %s", phone, bill_id)
    await deliver_to_customer(update.message, context, bill)


async def deliver_to_customer(message, context, bill):
    """Auto-send on WhatsApp if a number was given and the sender is linked; otherwise offer links."""
    note = None
    if bill.get("customer_phone"):
        paused = auto_send_paused()
        if not paused and await wa_sender.is_ready():
            await start_countdown(message, context, bill)
            return
        if paused:
            note = f"⏸️ Auto-send paused: {paused}. This protects the WhatsApp number from a ban."
    await send_customer_options(message, bill, note)


# ---------------------------------------------------------------- WhatsApp auto-send with countdown

PENDING = {}  # bill_id -> (countdown task, the Telegram status message)


def auto_send_paused():
    """Why auto-send must not run now (switch off or a limit reached), or None if it may."""
    if not store.AUTO_SEND:
        return "AUTO_SEND is off in .env"
    now, times = time.time(), store.whatsapp_send_times()
    if sum(sent > now - 3600 for sent in times) >= store.WA_MAX_PER_HOUR:
        return f"the limit of {store.WA_MAX_PER_HOUR} sends per hour is reached"
    if sum(sent > now - 86400 for sent in times) >= store.WA_MAX_PER_DAY:
        return f"the limit of {store.WA_MAX_PER_DAY} sends per day is reached"
    return None


def seconds_until_allowed():
    """Keep at least WA_MIN_GAP_SECONDS between two WhatsApp sends (+1 s: send times are whole seconds)."""
    times = store.whatsapp_send_times()
    return max(0, math.ceil(store.WA_MIN_GAP_SECONDS + 1 - (time.time() - times[-1]))) if times else 0


async def start_countdown(message, context, bill):
    old_status = cancel_send(context.chat_data.get("pending_send"))  # a new number replaces the old countdown
    if old_status:
        await old_status.edit_text("↪️ Number changed: not sent to this one. See below.")
    bill_id = bill["bill_id"]
    seconds = max(store.AUTO_SEND_SECONDS, seconds_until_allowed())
    phone = store.format_phone(bill["customer_phone"])
    status = await message.reply_text(
        f"📲 {bill_id} → {phone}\n"
        f"⏳ Sending on WhatsApp in {seconds} seconds…\n\n"
        "നമ്പർ തെറ്റാണെങ്കിൽ Cancel അമർത്തുക, അല്ലെങ്കിൽ \"വേണ്ട\" എന്ന് പറയുക.\n"
        "Wrong number? Tap Cancel or say \"cancel\". To fix it, send the right number.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✋ Cancel", callback_data=f"cancel:{bill_id}")]]),
    )
    store.set_send_status(bill_id, "pending", time.time() + seconds)
    context.chat_data["pending_send"] = bill_id
    PENDING[bill_id] = (asyncio.create_task(send_after(bill_id, seconds, status)), status)


async def send_after(bill_id, seconds, status):
    await asyncio.sleep(seconds)  # cancel_send() stops the task here
    PENDING.pop(bill_id, None)
    try:
        await send_now(bill_id, status)
    except Exception:  # a background task has no error handler: log it, don't lose it
        log.exception("Auto-send of %s failed", bill_id)
        store.set_send_status(bill_id, "failed")


async def send_now(bill_id, status):
    bill = store.get_bill(bill_id)
    phone = store.format_phone(bill["customer_phone"])
    try:
        await wa_sender.send_bill(bill)
    except wa_sender.SendError as error:
        store.set_send_status(bill_id, "failed")
        log.warning("WhatsApp send of %s failed: %s", bill_id, error)
        fallback = store.whatsapp_share_link(bill)
        await status.edit_text(
            f"❌ {bill_id} not sent to {phone}: {error}.\nTap below to send it from your own WhatsApp.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📲 Send on WhatsApp", url=fallback)]]),
        )
        return
    store.set_send_status(bill_id, "sent")
    store.mark_delivered(bill_id, "whatsapp")
    log.info("Sent %s to %s on WhatsApp", bill_id, bill["customer_phone"])
    await status.edit_text(f"✅ {bill_id} sent to {phone} on WhatsApp\nബിൽ വാട്സാപ്പിൽ അയച്ചു")


def cancel_send(bill_id):
    """Stop a countdown. Returns its Telegram status message, or None if nothing was pending."""
    pending = PENDING.pop(bill_id, None)
    if pending is None:
        return None
    task, status = pending
    task.cancel()
    store.set_send_status(bill_id, "cancelled")
    log.info("Cancelled WhatsApp send of %s", bill_id)
    return status


CANCELLED = "✋ {bill_id} not sent. റദ്ദാക്കി.\nSend the right number to send it again."


async def cancel_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    bill_id = query.data.split(":", 1)[1]
    status = cancel_send(bill_id)
    await query.answer("Cancelled" if status else "Already sent")
    if status:
        await query.edit_message_text(CANCELLED.format(bill_id=bill_id))


async def cancel_by_message(update, context):
    """The shopkeeper typed or said "cancel" / "വേണ്ട"."""
    bill_id = context.chat_data.get("pending_send")
    status = cancel_send(bill_id)
    if status:
        await status.edit_text(CANCELLED.format(bill_id=bill_id))
    else:
        await update.message.reply_text("Nothing to cancel. ഒന്നും അയക്കാനില്ല.")


async def send_customer_options(message, bill, note=None):
    """Tell the shopkeeper how to get the bill to the customer."""
    lines = [note] if note else []
    telegram_link = store.telegram_link(bill)
    if telegram_link:
        lines.append(f"Customer can scan the QR on the counter screen, or forward:\n{telegram_link}")
    whatsapp_link = store.whatsapp_share_link(bill)
    if not whatsapp_link:
        lines.append("💡 Send the customer's 10-digit phone number (say it or type it) to send this bill on WhatsApp.")
        await message.reply_text("\n\n".join(lines))
        return

    phone = store.format_phone(bill["customer_phone"])
    lines.insert(0, f"📲 {bill['bill_id']} → {phone}\n"
                    "നമ്പർ ശരിയാണോ? Check the number! If it's wrong, just type the right one.")
    if not store.PUBLIC_URL:
        lines.append("(Set PUBLIC_URL in .env to include a PDF link in the WhatsApp message.)")
    button = InlineKeyboardMarkup([[InlineKeyboardButton(f"📲 Send on WhatsApp to {phone}", url=whatsapp_link)]])
    try:
        await message.reply_text("\n\n".join(lines), reply_markup=button)
    except BadRequest as error:  # e.g. Telegram refuses a very long button link
        log.warning("WhatsApp button refused (%s); sending the link as text", error)
        await message.reply_text("\n\n".join(lines + [whatsapp_link]))


async def on_error(update, context: ContextTypes.DEFAULT_TYPE):
    """Any error in a handler: log it and tell the user, so the bot never goes silent."""
    log.error("Error while handling a Telegram message: %r", context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(TRY_AGAIN)
        except NetworkError:
            pass


# ---------------------------------------------------------------- Start / stop

async def start_bot():
    """Start long polling. Returns the Application, or None if no token is configured."""
    if not store.TELEGRAM_BOT_TOKEN:
        log.warning("TELEGRAM_BOT_TOKEN not set: Telegram bot is disabled.")
        return None
    app = (
        Application.builder()
        .token(store.TELEGRAM_BOT_TOKEN)
        .connect_timeout(15)  # defaults are 5 s, too short for slow shop/stage networks
        .read_timeout(30)
        .write_timeout(30)
        .media_write_timeout(60)
        .build()
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(cancel_button, pattern=r"^cancel:"))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, voice_note))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
    app.add_error_handler(on_error)
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    log.info("Telegram bot @%s is polling.", store.BOT_USERNAME or "?")
    return app


async def stop_bot(app):
    if app is None:
        return
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
