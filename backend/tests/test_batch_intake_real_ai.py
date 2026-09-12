"""Milestone 17 real-AI smoke: close-up package OCR + barcode, fully offline.

Runs the REAL local models — PaddleOCR and the pyzbar/system-zbar decoder —
against a synthetically rendered close-up package label (OpenCV text + a
Code-39 barcode). NO camera and NO network are used. This proves the
close-up, shopkeeper-assisted intake pipeline:

    rendered label image -> PaddleOCR text -> ExpiryParser -> ParsedProductMetadata
    rendered Code-39   -> pyzbar/zbar    -> barcode string

Marked `real_ai` (opt-in, slow) so the default suite stays fast. Skipped when
PaddleOCR/zbar cannot initialise.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.real_ai


def _make_label(barcode_value: str = "8901234567890"):
    from tests._barcode_fixture import package_photo_bytes

    return package_photo_bytes(
        barcode=barcode_value,
        text_lines=(
            "MRP: 14.00",
            "MFG: 12/03/2026",
            "EXP: 15/12/2026",
            "BATCH: M24031",
        ),
    )


def _open_ocr():
    from app.services.vision.ocr import OCRService

    try:
        return OCRService()
    except Exception as exc:
        pytest.skip(f"PaddleOCR unavailable in this environment: {exc}")


def _open_barcode_decoder():
    from app.services.batch_intake import BarcodeUnavailableError, PyZbarBarcodeDecoder

    try:
        return PyZbarBarcodeDecoder()
    except BarcodeUnavailableError as exc:
        pytest.skip(f"zbar/pyzbar unavailable in this environment: {exc}")


def test_real_ai_close_up_ocr_expiry_parser(tmp_path):
    """PaddleOCR reads a rendered package label; ExpiryParser structure it."""
    from datetime import date
    from decimal import Decimal

    import cv2

    from app.services.batch_intake.package_ocr import decode_image_bytes
    from app.services.product.expiry_parser import ExpiryParser
    from app.services.vision.ocr import OCRService  # noqa: F401 (see _open_ocr)

    ocr = _open_ocr()
    image = decode_image_bytes(_make_label())
    result = ocr.extract_text(image)
    assert len(result.items) >= 1, "expected at least one OCR text region"

    parsed = ExpiryParser().parse(result)
    assert parsed.expiry_date == date(2026, 12, 15), parsed.as_dict()
    assert parsed.manufacturing_date == date(2026, 3, 12), parsed.as_dict()
    assert parsed.batch_number == "M24031", parsed.as_dict()
    assert parsed.mrp == Decimal("14.00"), parsed.as_dict()

    assert bool(parsed) is True  # parser produced structured data


def test_real_ai_local_barcode_decode(tmp_path):
    """pyzbar/zbar decodes the Code-39 barcode from the rendered label."""
    import cv2

    from app.services.batch_intake.package_ocr import decode_image_bytes

    decoder = _open_barcode_decoder()
    image = decode_image_bytes(_make_label())
    reads = decoder.decode(image)
    assert reads, "expected the Code-39 barcode to decode"
    assert reads[0].data == "8901234567890"
    assert reads[0].symbology.upper() == "CODE39"