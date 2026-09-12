"""Product / shelf detection model adapter.

Wraps the existing Vision ShelfDetector (fine-tuned 55-class retail YOLO)
behind an injectable interface, with a deterministic fake for unit tests.

Product detections are INFORMATIONAL ONLY — they are never turned into
inventory mutations or batch creation by the Edge runtime.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger("storeye.edge.models.product")


@dataclass
class ProductFrameResult:
    class_name: str
    confidence: float
    bbox_xyxy: List[float]


class ProductDetectorModel:
    """Real ShelfDetector adapter."""

    def __init__(self, model_path: Optional[str] = None, conf: Optional[float] = None):
        from app.services.vision.shelf_detector import ShelfDetector

        self.conf = conf
        self._detector = ShelfDetector(model_path=model_path)

    @property
    def initialized(self) -> bool:
        return self._detector._model is not None

    def detect_frame(self, frame) -> List[ProductFrameResult]:
        result = self._detector.detect(frame, conf=self.conf or 0.25)
        return [
            ProductFrameResult(
                class_name=d.class_name,
                confidence=d.confidence,
                bbox_xyxy=list(d.bbox_xyxy),
            )
            for d in result.detections
        ]


class FakeProductDetector:
    """Deterministic fake product detector for unit tests."""

    def __init__(self, conf: Optional[float] = None):
        self.conf = conf or 0.88
        self._frame = 0

    @property
    def initialized(self) -> bool:
        return True

    def detect_frame(self, frame) -> List[ProductFrameResult]:
        self._frame += 1
        return [
            ProductFrameResult(
                class_name="Complan",
                confidence=self.conf,
                bbox_xyxy=[5.0, 5.0, 40.0, 70.0],
            ),
            ProductFrameResult(
                class_name="Glucon-D",
                confidence=self.conf - 0.1,
                bbox_xyxy=[60.0, 10.0, 100.0, 80.0],
            ),
        ]
