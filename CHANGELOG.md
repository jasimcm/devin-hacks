# Change log

Record each meaningful project change, newest first. Use a real timestamp with timezone,
for example `YYYY-MM-DDTHH:MM:SS+05:30`.

## 2026-10-25T06:00:00+05:30 — Confirm-before-bill, resend on WhatsApp, A4 printing

- Changed: `backend/parser.py`, `backend/bot.py`, `backend/pdf_gen.py`, `backend/printer.py`,
  `backend/store.py`, `backend/main.py`, `backend/whatsapp.py`, `.env.example`, `README.md`
- Why: the shopkeeper needed a check step before a bill exists, a way to send a bill to WhatsApp
  after the fact, a voice command to reprint, and receipts that print correctly on an A4 inkjet
  (HP Smart Tank 510) instead of only opening in Preview.
- Details:
  - Voice/text order now shows an item preview with ✅ OK / ✋ Cancel; the bill is created only on
    confirm. "ശരി"/"ok" as a voice note or text confirms too.
  - "send EB-0042 to whatsapp, number 98..." attaches a number to a named bill; "whatsapp-il
    ayakkoo" resends the last bill to its saved customer.
  - "ഇതൊന്ന് print ചെയ്യൂ" / "print EB-0013" reprints a bill; the reply shows the CUPS job id.
  - `PRINT_PAPER=a4` wraps the receipt at native 80mm size centred on A4 and prints with
    `lp -o media=A4 -o fit-to-page=false`; `receipt` keeps the old 80mm behaviour.
  - `printer.print_bill` returns (mode, detail); lp stderr is logged and reported by
    `POST /api/bills/{id}/print`.
- Validation: parser unit checks for summary/confirm/whatsapp/print intents (all pass);
  `build_a4_pdf` produces a 210×297mm MediaBox with the receipt rendered at native size
  (Quick Look render inspected); lp command args and job-id parsing verified with a stubbed
  subprocess; all modules compile; `/api/summary` verified end-to-end on a running server.
- Limitations: bill drafts live in memory only (a restart loses an unconfirmed preview);
  A4 printing not yet verified on the physical printer; very long bills could overflow one
  A4 page.
