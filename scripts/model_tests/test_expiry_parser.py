#!/usr/bin/env python3
"""Milestone 6 test: expiry/batch/MRP text parser.

Usage (from project root):
    python scripts/model_tests/test_expiry_parser.py

This parser is image-independent: it consumes raw OCR TEXT (a string or
an OCRResult) and needs no PaddleOCR model, so it runs instantly and
deterministically. Covers:
    - standard dates (DD/MM/YYYY)
    - different separators (/, -, .)
    - month/year expiry
    - batch extraction
    - MRP extraction
    - missing values
    - irrelevant unlabelled dates
    - OCR noise
    - ambiguous dates
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from app.services.product.expiry_parser import ExpiryParser, parse  # noqa: E402


def _show(title: str, raw: str) -> bool:
    r = parse(raw)
    d = r.as_dict()
    print(f"\n=== {title} ===")
    print(f"INPUT : {raw!r}")
    print(
        f"EXP   : {d['expiry_date']}  ({d['expiry_date_precision']})\n"
        f"MFG   : {d['manufacturing_date']}  ({d['manufacturing_date_precision']})\n"
        f"BATCH : {d['batch_number']}\n"
        f"MRP   : {d['mrp']}\n"
        f"CONF  : {d['confidence']}\n"
        f"WARN  : {d['warnings']}"
    )
    return bool(r)


def _check(desc: str, cond: bool) -> None:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {desc}")


def run() -> int:
    parser = ExpiryParser()
    failures = 0

    def expect(desc: str, cond: bool) -> None:
        nonlocal failures
        if not cond:
            failures += 1
        _check(desc, cond)

    # ---- Standard full label ------------------------------------------------
    r = parse("EXP 12/09/2026\nMFG 12/03/2026\nBATCH ABC123\nMRP Rs 45.00")
    _show("Standard full label", "EXP 12/09/2026\nMFG 12/03/2026\nBATCH ABC123\nMRP Rs 45.00")
    expect("expiry 2026-09-12 (day)", r.expiry_date == date(2026, 9, 12))
    expect("expiry precision day", r.expiry_date_precision == "day")
    expect("mfg 2026-03-12", r.manufacturing_date == date(2026, 3, 12))
    expect("batch ABC123", r.batch_number == "ABC123")
    expect("mrp 45.0", r.mrp == 45.0)

    # ---- MFD + USE BY + LOT ------------------------------------------------
    r = parse("MFD 05-01-2026\nUSE BY 05-01-2027\nLOT XY123")
    _show("MFD / USE BY / LOT", "MFD 05-01-2026\nUSE BY 05-01-2027\nLOT XY123")
    expect("mfg 2026-01-05 (dash)", r.manufacturing_date == date(2026, 1, 5))
    expect("expiry 2027-01-05", r.expiry_date == date(2027, 1, 5))
    expect("batch XY123", r.batch_number == "XY123")

    # ---- Month/year expiry ---------------------------------------------------
    r = parse("EXP 09/2027\nBATCH A1234")
    _show("Month/year expiry", "EXP 09/2027\nBATCH A1234")
    expect("expiry 2027-09-01 (month)", r.expiry_date == date(2027, 9, 1))
    expect("expiry precision month", r.expiry_date_precision == "month")
    expect("batch A1234", r.batch_number == "A1234")

    # ---- Dot separators + BEST BEFORE + LOT NO ------------------------------
    r = parse("BEST BEFORE 30.06.2027\nMFG 15.02.2026\nLOT NO A-77-1\nMRP Rs 12.50")
    _show("Dot separators / BEST BEFORE / LOT NO",
          "BEST BEFORE 30.06.2027\nMFG 15.02.2026\nLOT NO A-77-1\nMRP Rs 12.50")
    expect("expiry 2027-06-30 (dots)", r.expiry_date == date(2027, 6, 30))
    expect("mfg 2026-02-15", r.manufacturing_date == date(2026, 2, 15))
    expect("batch A-77-1", r.batch_number == "A-77-1")
    expect("mrp 12.5", r.mrp == 12.5)

    # ---- Irrelevant unlabelled dates -----------------------------------------
    r = parse("Phone: 9876543210\nContact 12-05-2020\nInvoice # 12345\nTotal Rs 500.00")
    _show("Irrelevant unlabelled dates",
          "Phone: 9876543210\nContact 12-05-2020\nInvoice # 12345\nTotal Rs 500.00")
    expect("no expiry (unlabelled)", r.expiry_date is None)
    expect("no mfg (unlabelled)", r.manufacturing_date is None)
    expect("no batch (unlabelled)", r.batch_number is None)
    expect("no mrp (unlabelled money)", r.mrp is None)

    # ---- OCR noise ------------------------------------------------------------
    r = parse("EYP 12/09/2026\nBATCHH AB123\nMRP: Rs 45.00")
    _show("OCR noise", "EYP 12/09/2026\nBATCHH AB123\nMRP: Rs 45.00")
    expect("noisy EXP (EYP) -> expiry", r.expiry_date == date(2026, 9, 12))
    expect("noisy BATCH (BATCHH) -> batch", r.batch_number == "AB123")
    expect("MRP: colon -> mrp", r.mrp == 45.0)

    # ---- Ambiguous date ---------------------------------------------------------
    r = parse("EXP 03/04/2026")
    _show("Ambiguous date", "EXP 03/04/2026")
    expect("ambiguity -> DD/MM/YYYY (2026-04-03)", r.expiry_date == date(2026, 4, 3))
    expect("ambiguity warning emitted", any("Ambiguous" in w for w in r.warnings))

    # ---- Missing values selected for builds ------------------------------------
    r = parse("BATCH Z9")
    _show("Missing/short batch", "BATCH Z9")
    expect("no expiry (missing)", r.expiry_date is None)
    expect("no short batch", r.batch_number is None)

    # ---- Value on next line ---------------------------------------------------
    r = parse("EXPIRY\n12/09/2026\nMRP\nRs 30.00")
    _show("Label then newline", "EXPIRY\n12/09/2026\nMRP\nRs 30.00")
    expect("expiry from next line", r.expiry_date == date(2026, 9, 12))
    expect("mrp from next line", r.mrp == 30.0)

    # ---- Empty / garbage --------------------------------------------------------
    r = parse("")
    expect("empty input -> all None", not bool(r) and r.expiry_date is None)
    r = parse("### no relevant fields ###")
    expect("garbage input -> all None", not bool(r))

    print("\n" + "=" * 50)
    print(f"RESULT: {'ALL PASS' if failures == 0 else f'{failures} FAILURE(S)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())