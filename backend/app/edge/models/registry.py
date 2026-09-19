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
        # YOLO-World detectors are prompt-conditioned: keyed by (path, prompts)
        # so cameras sharing the same vocabulary reuse one model + CLIP encoder.
        self._world: Dict[tuple, object] = {}

    # -- shared, stateless models ----------------------------------------
    def get_product_detector(self, model_path: Optional[str] = None):
        """Return the shared (cached) legacy 55-class shelf detector."""
        with self._lock:
            if self._product is None:
                from .product_detector import ProductDetectorModel

                self._product = ProductDetectorModel(
                    model_path=model_path
                    or str(default_model_path("models/shelf/shelf_model.pt"))
                )
                logger.info("Loaded shared product detector")
            return self._product

    def new_product_detector(
        self,
        *,
        detector: str = "world",
        model_path: Optional[str] = None,
        prompts: Optional[list] = None,
        conf: Optional[float] = None,
    ):
        """Create (or reuse) a product detector.

        The open-vocabulary (YOLO-World) detector owns a prompt set
        (`set_classes` mutates the model instance), so instances are cached by
        (model path, prompt tuple): cameras with identical vocabulary share one
        model + CLIP text encoder and memory stays bounded. Different prompts
        necessarily use different model instances.
        """
        if detector == "shelf":
            from .product_detector import ProductDetectorModel

            return ProductDetectorModel(
                model_path=model_path
                or str(default_model_path("models/shelf/shelf_model.pt")),
                conf=conf,
            )
        from .product_detector import WorldProductDetectorModel

        path = model_path or str(default_model_path("models/shelf/yolov8s-worldv2.pt"))
        key = (path, tuple(prompts or []))
        with self._lock:
            existing = self._world.get(key)
            if existing is not None:
                return existing
            model = WorldProductDetectorModel(
                model_path=path, prompts=prompts or [], conf=conf
            )
            self._world[key] = model
            return model

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
        if self._world:
            names.append("product/world")
        if self._ocr is not None:
            names.append("ocr")
        return names
