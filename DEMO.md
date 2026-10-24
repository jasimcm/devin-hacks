# Easy Bill: 2-minute demo script

**Cast:**
- **Presenter:** talks
- **Shopkeeper:** holds a phone with Telegram
- **Customer:** a judge or teammate with Telegram

**Screens:** the Mac shows the **counter screen** (`http://localhost:8000/counter.html`) on the projector.

## Before going on stage
- [ ] Run `./start.sh`. All three lines should be ✅ (bot polling, WhatsApp linked, public address).
- [ ] Only one copy may run: don't also start it on a teammate's laptop.
- [ ] `PRINTER=preview`, so the receipt opens on screen. Counter screen in full screen.
- [ ] Gemini daily quota checked in AI Studio
- [ ] The shopkeeper has already tapped **Start** in the bot chat
- [ ] One practice voice note sent. Then stop the server, delete `backend/bills.json` so bills start at EB-0001, and start it again.
- [ ] Mac and phones online. Have a phone hotspot ready as a backup.
- [ ] `whatsapp-sender` running (`npm start`) and http://localhost:3001 says **✅ Linked** (spare SIM)

## Three test sentences that work reliably

Send them as voice notes, or type them if the hall is noisy.

| # | Say this | Expected bill |
|---|---|---|
| 1 | **രണ്ട് കിലോ അരി, ഒരു സോപ്പ്, അര ലിറ്റർ പാൽ** | Rice 2 kg ₹110 · Soap 1 ₹40 · Milk 0.5 L ₹28 → **₹178** |
| 2 | **2 kg rice, 1 kg sugar, 1 litre coconut oil, 6 eggs** | ₹110 + ₹46 + ₹280 + ₹42 → **₹478** |
| 3 | **അര കിലോ പഞ്ചസാര, ഒരു പാക്കറ്റ് ചായപ്പൊടി, മൂന്ന് മുട്ട, ഒരു കിലോ ഉള്ളി** | ₹23 + ₹140 + ₹21 + ₹40 → **₹224** |

Speak at a normal pace with a short pause between items. A voice note takes about 5–10 seconds to become a bill.

## Script (≈ 2:00)

**0:00 – 0:20 · The problem** (Presenter)
> "In a small Kerala shop the owner adds up the bill by hand. It's slow, there are mistakes,
> and the customer gets no receipt. Billing software means typing, and these shopkeepers
> don't want to type. With Easy Bill, they just *say* the bill into their phone."

**0:20 – 0:55 · Voice note → bill** (Shopkeeper)
- Hold the mic in the bot chat and say sentence **1**.
- The bot replies "Listening…", then what it heard, the bill and the PDF.
- On the projector: the receipt opens, and the counter screen switches to **EB-0001** with the Malayalam
  item names, the total of ₹178 and two QR codes.

> Presenter: "Gemini only decides *which item* and *how much*. Prices always come from the shop's
> own price list, so the AI can never invent a price."

**0:55 – 1:35 · Customer pays and gets the bill** (Customer)
- Scan the **UPI QR** with GPay: shop name and ₹178 are already filled in (don't actually pay).
- Scan the **Telegram QR** and tap **Start**.
- The bot sends the bill and `EasyBill_EB-0001.pdf`, and the counter screen changes to **✅ Bill sent on Telegram**.

> "The customer gets a proper receipt on their phone, and the shop keeps a record of every bill."

**1:35 – 1:50 · Second bill, hands-free to a judge's WhatsApp** (Shopkeeper)
- Ask a judge for their number. Send sentence **2** ending with
  *"…6 eggs, send it on WhatsApp, the number is <judge's number>"*. **Say the number in English.**
- The counter screen shows EB-0002, ₹478, and the judge's number in large text with a 10-second countdown.
  Nobody touches anything.
- The judge's phone receives the bill PDF on WhatsApp, and the counter screen shows **✅ Bill sent on WhatsApp**.

> "If the number is wrong, the shopkeeper just says 'വേണ്ട' or sends the right number."

**1:45 – 2:00 · Close** (Presenter)
> "No typing, no billing software, no printer needed. The shopkeeper just talks. It's free to run:
> Telegram's free bot, Gemini's free tier, and a laptop at the counter. The same code also runs
> on WhatsApp. **മുതലാളി പറഞ്ഞാ മതി, ബാക്കി കിങ്കരൻ നോക്കിക്കോളും.**"

## If something breaks on stage

| Problem | Do this |
|---|---|
| Voice note gets no reply within 15 s | Type the same sentence to the bot. Typed text also works offline. |
| Bot doesn't answer at all | Check the server log. Is another copy of the server running somewhere? |
| No internet | Switch the Mac and phones to the phone hotspot. |
| Customer's Telegram is slow | Click **📄 View PDF** on the counter screen to show the receipt. |
