"""Shared model registry.

Loads heavy AI models lazily and reuses them so the process does not hold
duplicate copies of the same weights.

Stateless models (shelf detector, OCR) are shared singletons across cameras.
Person trackers MUST be per-camera because ByteTrack state (track ids) lives
inside the tracker and must NOT be shared between cameras — so the registry
creates one fresh person tracker per camera that requests it.

All paths come from local configuration; nothing is downloaded at runtime.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("storeye.edge.registry")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent


def default_model_path(relative: str) -> Path:
    return _PROJECT_ROOT / relative


class ModelRegistry:
    """Holds shared stateless models + hands out per-camera person trackers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._product: Optional[object] = None
        self._ocr: Optional[object] = None

    # -- shared, stateless models ----------------------------------------
    def get_product_detector(self, model_path: Optional[str] = None):
        """Return the shared (cached) shelf/product detector."""
        with self._lock:
            if self._product is None:
                from .product_detector import ProductDetectorModel

                self._product = ProductDetectorModel(
                    model_path=model_path
                    or str(default_model_path("models/shelf/shelf_model.pt"))
                )
                logger.info("Loaded shared product detector")
            return self._product

    def get_ocr(self, lang: str = "en"):
        """Return the shared (cached) OCR model."""
        with self._lock:
            if self._ocr is None:
                from .ocr import OCRModel

                self._ocr = OCRModel(lang=lang)
                logger.info("Loaded shared OCR model")
            return self._ocr

    # -- per-camera, stateful (tracker) -----------------------------------
    def new_person_tracker(self, model_path: Optional[str] = None):
        """Create a FRESH person tracker (isolated ByteTrack state per camera)."""
        from .person_detector import PersonTrackerModel

        return PersonTrackerModel(
            model_path=model_path or str(default_model_path("models/yolo/yolo11n.pt"))
        )

    def loaded_model_names(self) -> list:
        names = []
        if self._product is not None:
            names.append("product/shelf")
        if self._ocr is not None:
            names.append("ocr")
        return names
