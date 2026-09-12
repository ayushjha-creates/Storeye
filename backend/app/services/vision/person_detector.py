"""YOLO11n-based person/general object detector for Storeye.

Responsibilities (keep minimal):
- Load a YOLO11n model once.
- Run inference on an image/frame.
- Return structured detections (class, confidence, bounding box).

This module must NOT contain database, business, billing, messaging or
expiry/FEFO logic. It is a pure computer-vision service.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

logger = logging.getLogger("storeye.vision.person_detector")

# COCO class 0 is "person"
PERSON_CLASS_ID = 0
COCO_CLASS_NAMES = {
    0: "person",
}


@dataclass
class Detection:
    """A single detected object."""

    class_id: int
    class_name: str
    confidence: float
    bbox_xyxy: List[float]  # [x1, y1, x2, y2] in pixel coordinates

    def area(self) -> float:
        x1, y1, x2, y2 = self.bbox_xyxy
        return max(0.0, (x2 - x1)) * max(0.0, (y2 - y1))


@dataclass
class DetectionResult:
    """Result of one inference pass on a single frame."""

    detections: List[Detection] = field(default_factory=list)

    def persons(self) -> List[Detection]:
        return [d for d in self.detections if d.class_id == PERSON_CLASS_ID]

    def __len__(self) -> int:
        return len(self.detections)


class PersonDetector:
    """Thin wrapper around an Ultralytics YOLO11n model.

    Example:
        detector = PersonDetector()          # auto-locates the model file
        result = detector.detect(frame)      # frame is a numpy BGR array
        for p in result.persons():
            print(p.confidence, p.bbox_xyxy)
    """

    def __init__(
        self,
        model_path: Optional[str | Path] = None,
        device: Optional[str] = None,
        person_only: bool = True,
    ) -> None:
        """
        Args:
            model_path: Path to the .pt weights. Defaults to
                <project_root>/models/yolo/yolo11n.pt.
            device: 'cpu', 'mps', 'cuda', or None to auto-select.
            person_only: If True, filters results to person detections only.
        """
        self.model_path = Path(model_path) if model_path else self._default_model_path()
        self.device = device or self._auto_device()
        self.person_only = person_only
        self._model: Any = None
        self.load()

    # ------------------------------------------------------------------
    # Path & device helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _project_root() -> Path:
        # backend/app/services/vision/person_detector.py -> project root
        # (backend/app/services/vision -> backend/app/services -> backend/app
        #  -> backend -> <project root>)
        return Path(__file__).resolve().parent.parent.parent.parent.parent

    @staticmethod
    def _default_model_path() -> Path:
        return PersonDetector._project_root() / "models" / "yolo" / "yolo11n.pt"

    @staticmethod
    def _auto_device() -> str:
        import torch

        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
        return "cpu"

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def load(self) -> None:
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Model file not found: {self.model_path}. "
                "Expected a YOLO11n weights file at "
                "models/yolo/yolo11n.pt"
            )
        if self.model_path.stat().st_size == 0:
            raise ValueError(
                f"Model file is empty (0 bytes): {self.model_path}. "
                "Replace it with valid YOLO11n weights."
            )
        try:
            from ultralytics import YOLO

            self._model = YOLO(str(self.model_path))
            logger.info(
                "Loaded %s on device=%s", self.model_path.name, self.device
            )
        except Exception as exc:  # pragma: no cover - defensive
            raise RuntimeError(
                f"Failed to load YOLO model from {self.model_path}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------
    def detect(self, frame: Any) -> DetectionResult:
        """Run detection on a single BGR image/frame.

        Args:
            frame: A numpy array (H, W, 3) in BGR order.

        Returns:
            DetectionResult with one Detection per kept box.
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        results = self._model.predict(
            source=frame,
            device=self.device,
            verbose=False,
            conf=0.25,  # base threshold; callers may filter further
        )
        return self._parse_results(results)

    def _parse_results(self, results: Any) -> DetectionResult:
        """Convert YOLO result boxes into structured Detections."""
        result = DetectionResult()
        if not results:
            return result

        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return result

        names: dict = results[0].names or {}
        xyxy = boxes.xyxy.cpu().numpy()
        confs = boxes.conf.cpu().numpy()
        cls_ids = boxes.cls.cpu().numpy().astype(int)

        for (x1, y1, x2, y2), conf, cid in zip(xyxy, confs, cls_ids):
            if self.person_only and cid != PERSON_CLASS_ID:
                continue
            result.detections.append(
                Detection(
                    class_id=int(cid),
                    class_name=names.get(int(cid), COCO_CLASS_NAMES.get(int(cid), "unknown")),
                    confidence=float(conf),
                    bbox_xyxy=[float(x1), float(y1), float(x2), float(y2)],
                )
            )
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def annotate(self, frame_bgr: Any, detections: DetectionResult, color=(0, 255, 0)) -> Any:
        """Draw bounding boxes + labels on a copy of the frame (BGR in/out)."""
        import cv2

        out = frame_bgr.copy()
        for d in detections.detections:
            x1, y1, x2, y2 = (int(v) for v in d.bbox_xyxy)
            cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
            label = f"{d.class_name} {d.confidence:.2f}"
            cv2.putText(
                out,
                label,
                (x1, max(y1 - 6, 12)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                1,
                cv2.LINE_AA,
            )
        return out