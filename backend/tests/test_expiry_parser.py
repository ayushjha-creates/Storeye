"""Unit tests for the Storeye expiry/batch/MRP parser.

These tests are wholly independent of PaddleOCR/images: they feed raw
strings (and a lightweight OCRResult-shaped object) directly to the
parser, making them fast and deterministic.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.product.expiry_parser import ExpiryParser, parse
from app.services.vision.ocr import OCRResult, OCRTextItem

# Pure unit tests: no database required.
pytestmark = pytest.mark.no_db


# ---------------------------------------------------------------------------
# Standard dates / labels
# ---------------------------------------------------------------------------
def test_full_label_dd_mm_yyyy():
    r = parse("EXP 12/09/2026\nMFG 12/03/2026\nBATCH ABC123\nMRP Rs 45.00")
    assert r.expiry_date == date(2026, 9, 12)
    assert r.expiry_date_precision == "day"
    assert r.manufacturing_date == date(2026, 3, 12)
    assert r.batch_number == "ABC123"
    assert r.mrp == Decimal("45.00")


def test_mfd_use_by_dash_separator():
    r = parse("MFD 05-01-2026\nUSE BY 05-01-2027\nLOT XY123")
    assert r.manufacturing_date == date(2026, 1, 5)
    assert r.expiry_date == date(2027, 1, 5)
    assert r.batch_number == "XY123"


def test_dot_separator_best_before():
    r = parse("BEST BEFORE 30.06.2027\nMFG 15.02.2026")
    assert r.expiry_date == date(2027, 6, 30)
    assert r.manufacturing_date == date(2026, 2, 15)


# ---------------------------------------------------------------------------
# Month/year expiry
# ---------------------------------------------------------------------------
def test_month_year_expiry():
    r = parse("EXP 09/2027")
    # represented as first day of month with month precision (no invented day)
    assert r.expiry_date == date(2027, 9, 1)
    assert r.expiry_date_precision == "month"
    assert any("MONTH/YEAR" in w for w in r.warnings)


def test_day_precision_by_default():
    r = parse("EXP 12/09/2026")
    assert r.expiry_date_precision == "day"


# ---------------------------------------------------------------------------
# Batch extraction
# ---------------------------------------------------------------------------
def test_batch_variants():
    assert parse("BATCH A1234").batch_number == "A1234"
    assert parse("LOT NO A-77-1").batch_number == "A-77-1"
    assert parse("BATCH NUMBER XY-99\n").batch_number == "XY-99"


def test_batch_ignores_digit_only_and_dates():
    # a pure number and a pure date-like value should not be captured as a batch
    r = parse("BATCH 9876543210")
    assert r.batch_number is None
    r2 = parse("BATCH 12/09/2026")
    assert r2.batch_number is None


# ---------------------------------------------------------------------------
# MRP extraction
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "line,expected",
    [
        ("MRP Rs 45.00", "45.00"),
        ("MRP: INR 12.50", "12.50"),
        ("MRP 500", "500"),
    ],
)
def test_mrp_formats(line, expected):
    assert parse(line).mrp == Decimal(expected)


# ---------------------------------------------------------------------------
# Missing values & irrelevant dates
# ---------------------------------------------------------------------------
def test_missing_values_are_none():
    r = parse("BATCH Z9")
    assert r.expiry_date is None
    assert r.manufacturing_date is None
    assert r.batch_number is None
    assert r.mrp is None
    assert not r  # bool(ParsedProductMetadata) False when nothing extracted


def test_irrelevant_unlabelled_dates_ignored():
    r = parse("Phone: 9876543210\nContact 12-05-2020\nInvoice # 12345\nTotal Rs 500.00")
    assert r.expiry_date is None
    assert r.manufacturing_date is None
    assert r.batch_number is None
    assert r.mrp is None


def test_no_partial_invention_for_incomplete_date():
    # 2-digit second part is too ambiguous to be a confident full date
    r = parse("EXP 12/09")
    assert r.expiry_date is None


def test_empty_and_garbage_input():
    assert not parse("")
    assert not parse("### nothing relevant ###")


# ---------------------------------------------------------------------------
# OCR noise (conservative)
# ---------------------------------------------------------------------------
def test_ocr_label_noise_accepted_when_value_valid():
    r = parse("EYP 12/09/2026\nBATCHH AB123\nMRP: Rs 45.00")
    assert r.expiry_date == date(2026, 9, 12)
    assert r.batch_number == "AB123"
    assert r.mrp == Decimal("45.00")


def test_ocr_noise_does_not_create_value_in_absence():
    # label noise alone, with no parseable value, must not yield a result
    r = parse("BATCHH")
    assert r.batch_number is None


# ---------------------------------------------------------------------------
# Ambiguous dates
# ---------------------------------------------------------------------------
def test_ambiguous_date_defaults_to_ddmmyyyy_with_warning():
    r = parse("EXP 03/04/2026")
    assert r.expiry_date == date(2026, 4, 3)  # DD/MM/YYYY (India)
    assert any("Ambiguous" in w for w in r.warnings)


def test_33_day_rejected():
    # day > 31 invalid -> no expiry
    r = parse("EXP 33/04/2026")
    assert r.expiry_date is None


def test_month_13_rejected():
    r = parse("EXP 12/13/2026")
    assert r.expiry_date is None


# ---------------------------------------------------------------------------
# Value on a following line (OCR box layout)
# ---------------------------------------------------------------------------
def test_label_value_on_next_line():
    r = parse("EXPIRY\n12/09/2026\nMRP\nRs 30.00")
    assert r.expiry_date == date(2026, 9, 12)
    assert r.mrp == Decimal("30.00")


def test_manufacturing_label_on_next_line():
    r = parse("MFG\n11-11-2025\nLOT 77XX")
    assert r.manufacturing_date == date(2025, 11, 11)
    assert r.batch_number == "77XX"


# ---------------------------------------------------------------------------
# Input type independence (string vs OCRResult)
# ---------------------------------------------------------------------------
def test_accepts_ocrresult_directly():
    result = OCRResult()
    for text, conf in [
        ("EXP 12/09/2026", 0.98),
        ("BATCH ABC123", 0.96),
        ("MRP Rs 45.00", 0.94),
    ]:
        result.items.append(OCRTextItem(text=text, confidence=conf, bbox_xyxy=[0, 0, 1, 1]))
    r = parse(result)
    assert r.expiry_date == date(2026, 9, 12)
    assert r.batch_number == "ABC123"
    assert r.mrp == Decimal("45.00")
    # confidence averaged over contributing items
    assert r.confidence == round((0.98 + 0.96 + 0.94) / 3, 4)


def test_raw_text_preserved_for_audit():
    raw = "EXP 12/09/2026\nMFG 12/03/2026\nBATCH ABC123\nMRP Rs 45.00"
    assert parse(raw).raw_text == raw


def test_parse_entrypoint_returns_instance():
    from app.services.product.expiry_parser import ParsedProductMetadata
    assert isinstance(parse("EXP 01/02/2026"), ParsedProductMetadata)