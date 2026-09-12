"""Pretrained shelf/product object detector for Storeye.

Responsibilities (keep minimal):
- Load a fine-tuned retail-product YOLO checkpoint.
- Run inference on a shelf image/frame.
- Return structured detections (class, confidence, bounding box).

This module must NOT contain database, business, billing, messaging,
inventory, planogram, or FEFO logic. It is a pure computer-vision service.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("storeye.vision.shelf_detector")


@dataclass
class Detection:
    """A single detected shelf product/object."""

    class_id: int
    class_name: str
    confidence: float
    bbox_xyxy: List[float]  # [x1, y1, x2, y2] pixel coordinates

    def area(self) -> float:
        x1, y1, x2, y2 = self.bbox_xyxy
        return max(0.0, (x2 - x1)) * max(0.0, (y2 - y1))


@dataclass
class DetectionResult:
    """Result of one shelf inference pass."""

    detections: List[Detection] = field(default_factory=list)
    img_shape: List[int] = field(default_factory=lambda: [0, 0])  # [H, W]

    def by_class(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for d in self.detections:
            counts[d.class_name] = counts.get(d.class_name, 0) + 1
        return counts

    def __len__(self) -> int:
        return len(self.detections)


class ShelfDetector:
    """Thin wrapper around a fine-tuned YOLO retail-product detector.

    The checkpoint (models/shelf/shelf_model.pt) is a standard Ultralytics
    YOLO task='detect' model with 55 custom product classes
    (Indian FMCG: Complan, Everyuth, Glucon-D, Nutralite, Sugar-Free, etc.)

    Example:
        detector = ShelfDetector()
        result = detector.detect(shelf_image)
        print(len(result), 'products found')
    """

    def __init__(
        self,
        model_path: Optional[str | Path] = None,
        device: Optional[str] = None,
    ) -> None:
        """
        Args:
            model_path: Path to the .pt weights. Defaults to
                <project_root>/models/shelf/shelf_model.pt.
            device: 'cpu', 'mps', 'cuda', or None to auto-select.
        """
        self.model_path = Path(model_path) if model_path else self._default_model_path()
        self.device = device or self._auto_device()
        self._model: Any = None
        self._names: Dict[int, str] = {}
        self._num_classes: int = 0
        self.load()

    # ------------------------------------------------------------------
    # Path & device helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _project_root() -> Path:
        # backend/app/services/vision/shelf_detector.py -> project root
        return Path(__file__).resolve().parent.parent.parent.parent.parent

    @staticmethod
    def _default_model_path() -> Path:
        return ShelfDetector._project_root() / "models" / "shelf" / "shelf_model.pt"

    @staticmethod
    def _auto_device() -> str:
        import torch

        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
        return "cpu"

    # ------------------------------------------------------------------
    # Loading & metadata
    # ------------------------------------------------------------------
    def load(self) -> None:
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Shelf model not found: {self.model_path}. "
                "Expected a valid Ultralytics checkpoint at "
                "models/shelf/shelf_model.pt"
            )
        if self.model_path.stat().st_size == 0:
            raise ValueError(
                f"Shelf model is empty (0 bytes): {self.model_path}. "
                "Replace it with a valid trained checkpoint."
            )
        try:
            from ultralytics import YOLO

            self._model = YOLO(str(self.model_path))
            self._names = dict(self._model.names)  # {0: 'Complan...', ...}
            self._num_classes = len(self._names)

            logger.info(
                "Loaded %s | task=%s | classes=%d | device=%s",
                self.model_path.name,
                getattr(self._model, "task", "detect"),
                self._num_classes,
                self.device,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load shelf model from {self.model_path}: {exc}"
            ) from exc

    @property
    def class_names(self) -> Dict[int, str]:
        return dict(self._names)

    @property
    def num_classes(self) -> int:
        return self._num_classes

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------
    def detect(self, frame: Any, conf: float = 0.25, iou: float = 0.5) -> DetectionResult:
        """Run detection on a single BGR image/frame.

        Args:
            frame: numpy array (H, W, 3) in BGR order.
            conf: Confidence threshold.
            iou: NMS IoU threshold.

        Returns:
            DetectionResult with one Detection per kept box.
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        import cv2

        h, w = frame.shape[:2]
        results = self._model.predict(
            source=frame,
            device=self.device,
            imgsz=640,
            conf=conf,
            iou=iou,
            verbose=False,
        )
        return self._parse_results(results, frame_h=h, frame_w=w)

    def _parse_results(self, results: Any, frame_h: int, frame_w: int) -> DetectionResult:
        result = DetectionResult(img_shape=[frame_h, frame_w])
        if not results:
            return result

        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return result

        names: dict = results[0].names or self._names
        xyxy = boxes.xyxy.cpu().numpy()
        confs = boxes.conf.cpu().numpy()
        cls_ids = boxes.cls.cpu().numpy().astype(int)

        for (x1, y1, x2, y2), conf, cid in zip(xyxy, confs, cls_ids):
            cid_int = int(cid)
            cname = str(names.get(cid_int, self._names.get(cid_int, f"class_{cid_int}")))
            result.detections.append(
                Detection(
                    class_id=cid_int,
                    class_name=cname,
                    confidence=float(conf),
                    bbox_xyxy=[float(x1), float(y1), float(x2), float(y2)],
                )
            )
        return result

    # ------------------------------------------------------------------
    # Annotation
    # ------------------------------------------------------------------
    def annotate(self, frame_bgr: Any, detections: DetectionResult,
                 color=(0, 255, 255)) -> Any:
        """Draw boxes + labels. Returns a new BGR frame."""
        import cv2

        out = frame_bgr.copy()
        for d in detections.detections:
            x1, y1, x2, y2 = (int(v) for v in d.bbox_xyxy)
            cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
            label = f"{d.class_name} {d.confidence:.2f}"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            top = max(y1 - th - 8, 0)
            cv2.rectangle(out, (x1, top), (x1 + tw, top + th + 6), color, -1)
            cv2.putText(
                out,
                label,
                (x1, top + th + 3),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 0, 0),
                1,
                cv2.LINE_AA,
            )
        return out