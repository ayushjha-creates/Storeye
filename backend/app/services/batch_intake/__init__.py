"""Smart Batch Receiving: close-up, shopkeeper-assisted stock intake.

This package implements the Milestone-17 architecture (see
`docs/edge-ai.md` and `docs/milestone_17_smart_batch_receiving.md`):

    OLD ASSUMPTION (removed)
        Continuous CCTV frames -> OCR -> expiry/batch data. This was
        unreliable at distance and conflated monitoring with inventory.

    NEW ARCHITECTURE (this package)
        Close-up package photo  -> local barcode decode (GTIN/EAN/UPC/Code-39)
                                  -> local PaddleOCR text extraction
                                  -> ExpiryParser (existing, unchanged)
                                  -> editable CANDIDATE (never committed)
                                  -> shopkeeper confirmation (quantity typed)
                                  -> BatchService/InventoryService (atomic)
                                  -> PostgreSQL

Guarantees
----------
- Scan NEVER mutates inventory, batches or products (read-only + parse).
- Barcode only resolves the LOCAL Product catalog; unknown barcode surfaces a
  "Product not found" state instead of auto-creating a product.
- Human confirmation is required; quantity is always entered by the shopkeeper.
- Confirmation reuses the existing BatchService/InventoryService so batch and
  inventory/movement mutation is single-transaction (all-or-nothing).
- Everything runs offline on-device: local decode (pyzbar/zbar), local OCR
  (PaddleOCR), local parser. No cloud OCR/barcode lookup.
"""

from .errors import (
    BarcodeUnavailableError,
    BatchIntakeError,
    ImageDecodeError,
    ImageQualityError,
    OcrUnavailableError,
    ScanValidationError,
)
from .candidate import DecodedBarcode, PackageScan, PackageScanCandidate
from .barcode_decoder import (
    BarcodeDecoder,
    FakeBarcodeDecoder,
    PyZbarBarcodeDecoder,
    make_barcode_decoder,
)
from .package_ocr import (
    PackageOCRProcessor,
    QualityGateConfig,
)
from .batch_intake_service import BatchIntakeService

__all__ = [
    "BarcodeDecoder",
    "BarcodeUnavailableError",
    "BatchIntakeError",
    "BatchIntakeService",
    "DecodedBarcode",
    "FakeBarcodeDecoder",
    "ImageDecodeError",
    "ImageQualityError",
    "OcrUnavailableError",
    "PackageOCRProcessor",
    "PackageScan",
    "PackageScanCandidate",
    "PyZbarBarcodeDecoder",
    "QualityGateConfig",
    "ScanValidationError",
    "make_barcode_decoder",
]