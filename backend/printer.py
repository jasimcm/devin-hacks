"""Print a bill's receipt on the Mac.

Set PRINTER in .env:
  (empty)        save the PDF in backend/printed/ only
  preview        save it and open it in Preview (good for a demo with no printer)
  <printer name> send it to that printer with `lp`. List names with:  lpstat -p
"""
import logging
import subprocess

import pdf_gen
import store

log = logging.getLogger("easybill.printer")

PRINTED_DIR = store.BACKEND_DIR / "printed"


def print_bill(bill):
    PRINTED_DIR.mkdir(exist_ok=True)
    path = PRINTED_DIR / f"EasyBill_{bill['bill_id']}.pdf"
    path.write_bytes(pdf_gen.build_pdf(bill))

    if store.PRINTER == "preview":
        command = ["open", str(path)]
    elif store.PRINTER:
        command = ["lp", "-d", store.PRINTER, "-o", "fit-to-page", str(path)]
    else:
        log.info("Saved %s (no PRINTER set)", path.name)
        return path

    try:
        subprocess.run(command, check=True, capture_output=True, timeout=20)
        log.info("Printed %s with %s", path.name, command[0])
    except (OSError, subprocess.SubprocessError) as error:
        log.error("Printing %s failed: %s", path.name, error)
    return path
