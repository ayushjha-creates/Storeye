"""Domain exceptions for Smart Batch Intake.

These are mapped onto HTTP responses in `app/api/errors.py`:

    ImageDecodeError / ImageQualityError / ScanValidationError  422
    OcrUnavailableError / BarcodeUnavailableError               503
"""

from __future__ import annotations


class BatchIntakeError(Exception):
    """Base class for batch-intake domain errors."""


class ImageDecodeError(BatchIntakeError):
    """The uploaded bytes are not a decodable image (or too large)."""


class ImageQualityError(BatchIntakeError):
    """The image is too small / too low resolution for close-up OCR."""


class ScanValidationError(BatchIntakeError):
    """Scan-time input failed validation (e.g. unsupported file type)."""


class OcrUnavailableError(BatchIntakeError):
    """Close-up OCR (PaddleOCR) could not be initialised in this environment."""


class BarcodeUnavailableError(BatchIntakeError):
    """No working local barcode decoder (pyzbar/zbar) is available."""