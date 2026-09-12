"""Edge model wrappers.

Thin, injectable adapters around the existing Storeye AI services
(app.services.vision). They give the Edge runtime a stable interface while
letting tests inject lightweight fakes — the heavy real models are never loaded
in normal unit tests.

Each wrapper holds the heavy model as a lazily-initialized singleton so the
runtime can reuse one copy across cameras (resource safety).
"""

from __future__ import annotations

from .person_detector import PersonTrackerModel, FakePersonTracker, PersonFrameResult
from .product_detector import ProductDetectorModel, FakeProductDetector
from .ocr import OCRModel, FakeOCR

__all__ = [
    "PersonTrackerModel",
    "FakePersonTracker",
    "PersonFrameResult",
    "ProductDetectorModel",
    "FakeProductDetector",
    "OCRModel",
    "FakeOCR",
]
