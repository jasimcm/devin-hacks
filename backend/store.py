"""Shared config, inventory and bill storage (bills.json). Used by main.py and the bots."""
import json
import os
import secrets
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
ROOT_DIR = BACKEND_DIR.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
INVENTORY_FILE = BACKEND_DIR / "inventory.json"
BILLS_FILE = BACKEND_DIR / "bills.json"

load_dotenv(ROOT_DIR / ".env")


def env(name, default=""):
    return os.getenv(name, default).strip()


TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN")
BOT_USERNAME = env("BOT_USERNAME").lstrip("@")
GEMINI_API_KEY = env("GEMINI_API_KEY")
GEMINI_MODEL = env("GEMINI_MODEL", "gemini-flash-lite-latest")
SHOP_NAME = env("SHOP_NAME", "Easy Bill Stores")
SHOP_ADDRESS = env("SHOP_ADDRESS", "Main Road, Kerala")
SHOP_PHONE = env("SHOP_PHONE", "+91 90000 00000")
UPI_VPA = env("UPI_VPA", "shop@upi")

WHATSAPP_TOKEN = env("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = env("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_NUMBER = "".join(ch for ch in env("WHATSAPP_NUMBER") if ch.isdigit())
WHATSAPP_VERIFY_TOKEN = env("WHATSAPP_VERIFY_TOKEN", "easybill-verify")
WHATSAPP_APP_SECRET = env("WHATSAPP_APP_SECRET")
WHATSAPP_API_VERSION = env("WHATSAPP_API_VERSION", "v23.0")

PRINTER = env("PRINTER")

# WhatsApp sender (whatsapp-sender/, Node) and the seconds to wait before it sends, so the
# shopkeeper can check the number and cancel
WA_SENDER_URL = env("WA_SENDER_URL", "http://127.0.0.1:3001").rstrip("/")
AUTO_SEND_SECONDS = int(env("AUTO_SEND_SECONDS", "10"))
# Ban safety for the linked number: an on/off switch, send limits, and a minimum gap between sends
AUTO_SEND = env("AUTO_SEND", "on").lower() not in ("off", "0", "no", "false")
WA_MAX_PER_HOUR = int(env("WA_MAX_PER_HOUR", "10"))
WA_MAX_PER_DAY = int(env("WA_MAX_PER_DAY", "30"))
WA_MIN_GAP_SECONDS = int(env("WA_MIN_GAP_SECONDS", "20"))

# Public HTTPS address of this server (e.g. a Cloudflare tunnel), used for the PDF link in WhatsApp messages
PUBLIC_URL = env("PUBLIC_URL").rstrip("/")

with open(INVENTORY_FILE, encoding="utf-8") as f:
    INVENTORY = json.load(f)
INVENTORY_BY_ID = {item["id"]: item for item in INVENTORY}

_lock = threading.Lock()


def price_items(items):
    """Turn [{item_id, qty}] into priced bill lines. Prices ALWAYS come from inventory.json."""
    lines = []
    for entry in items:
        item = INVENTORY_BY_ID.get(entry["item_id"])
        qty = round(float(entry["qty"]), 3)
        if item is None or qty <= 0:
            continue
        lines.append({
            "item_id": item["id"],
            "name_en": item["name_en"],
            "name_ml": item["name_ml"],
            "qty": qty,
            "unit": item["unit"],
            "price": item["price"],
            "line_total": round(qty * item["price"], 2),
        })
    total = round(sum(line["line_total"] for line in lines), 2)
    return lines, total


def upi_link(bill):
    return (
        f"upi://pay?pa={quote(UPI_VPA, safe='@.')}&pn={quote(SHOP_NAME)}"
        f"&am={bill['total']:.2f}&cu=INR&tn={quote(bill['bill_id'])}"
    )


def telegram_link(bill):
    if not BOT_USERNAME:
        return None
    return f"https://t.me/{BOT_USERNAME}?start={bill['bill_id']}"


def whatsapp_link(bill):
    """Opens WhatsApp with "BILL EB-0042" typed in; the customer taps send and the bot replies."""
    if not WHATSAPP_NUMBER:
        return None
    return f"https://wa.me/{WHATSAPP_NUMBER}?text={quote('BILL ' + bill['bill_id'])}"


def pdf_share_link(bill):
    """Private link to the PDF: the random key stops people guessing other customers' bills."""
    if not PUBLIC_URL or not bill.get("share_key"):  # bills made before share keys existed have none
        return None
    return f"{PUBLIC_URL}/share/{bill['bill_id']}/{bill['share_key']}"


def whatsapp_share_link(bill):
    """Opens the shopkeeper's own WhatsApp in a chat with the customer, with the bill typed in."""
    if not bill.get("customer_phone"):
        return None
    text = bill_summary(bill)
    pdf_link = pdf_share_link(bill)
    if pdf_link:
        text += f"\n\n📄 PDF: {pdf_link}"
    return f"https://wa.me/{bill['customer_phone']}?text={quote(text)}"


def format_phone(phone):
    """919847012345 -> +91 98470 12345"""
    return f"+{phone[:2]} {phone[2:7]} {phone[7:]}"


def bill_summary(bill):
    """Short text version of the bill for Telegram and WhatsApp messages."""
    lines = [f"🧾 {SHOP_NAME}", f"Bill {bill['bill_id']}", ""]
    for item in bill["items"]:
        lines.append(f"• {item['name_en']} × {item['qty']:g} = ₹{item['line_total']:.2f}")
    lines += ["", f"Total: ₹{bill['total']:.2f}", f"UPI: {UPI_VPA}", "നന്ദി! Thank you for shopping with us."]
    return "\n".join(lines)


def _load_bills():
    if not BILLS_FILE.exists():
        return {}
    with open(BILLS_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save_bills(bills):
    tmp = BILLS_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(bills, f, ensure_ascii=False, indent=2)
    tmp.replace(BILLS_FILE)


def create_bill(lines, total, channel="web", transcript="", customer_phone=None):
    with _lock:
        bills = _load_bills()
        bill_id = f"EB-{len(bills) + 1:04d}"
        bill = {
            "bill_id": bill_id,
            "share_key": secrets.token_urlsafe(8),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "channel": channel,
            "transcript": transcript,
            "customer_phone": customer_phone,
            "items": lines,
            "total": total,
            "delivered": False,
            "delivered_at": None,
            "delivered_via": None,
        }
        bills[bill_id] = bill
        _save_bills(bills)
        return bill


def get_bill(bill_id):
    with _lock:
        return _load_bills().get(bill_id.upper())


def set_customer_phone(bill_id, phone):
    with _lock:
        bills = _load_bills()
        bills[bill_id]["customer_phone"] = phone
        _save_bills(bills)
        return bills[bill_id]


def set_send_status(bill_id, status, send_at=None):
    """WhatsApp auto-send progress for the counter screen: pending / sent / cancelled / failed."""
    with _lock:
        bills = _load_bills()
        bills[bill_id]["send_status"] = status
        bills[bill_id]["send_at"] = send_at
        _save_bills(bills)


def whatsapp_send_times():
    """When each bill was auto-sent on WhatsApp (seconds since 1970), oldest first."""
    with _lock:
        bills = _load_bills()
    return sorted(
        datetime.fromisoformat(bill["delivered_at"]).timestamp()
        for bill in bills.values()
        if bill.get("send_status") == "sent" and bill.get("delivered_at")
    )


def latest_bill():
    with _lock:
        bills = _load_bills()
        return bills[max(bills)] if bills else None


def mark_delivered(bill_id, via):
    with _lock:
        bills = _load_bills()
        if bill_id in bills:
            bills[bill_id]["delivered"] = True
            bills[bill_id]["delivered_at"] = datetime.now().isoformat(timespec="seconds")
            bills[bill_id]["delivered_via"] = via
            _save_bills(bills)
