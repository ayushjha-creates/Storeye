"""Open-vocabulary (zero-shot) retail-product detector on Ultralytics YOLO-World.

The fine-tuned 55-class checkpoint (`models/shelf/shelf_model.pt`) can only see
the FMCG SKUs it was trained on — it has no biscuit / generic-package class, so
a real store's shelves mostly produce nothing. YOLO-World is *text-conditioned*:
give it the store's own product prompts ("biscuit packet", "milk carton", ...)
and it detects those objects on the current shelf frame.

This is REAL inference over the current frame — never fabricated counts. It is
zero-shot, so it only finds products an operator (or the store catalog) listed
as prompts, and accuracy depends on how well a prompt describes the physical
packaging. Unlisted products are still not counted, and nothing is guessed.

First load needs the CLIP text-encoder weights (`ViT-B-32.pt`, ~338 MB) so the
prompt words can be encoded; Ultralytics downloads them once to
`weights/clip/ViT-B-32.pt` (relative to the process CWD). After that first
download the detector runs fully offline. This module must NOT contain database
or business logic — it is a pure computer-vision service.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .shelf_detector import Detection, DetectionResult

logger = logging.getLogger("storeye.vision.world_detector")

# Default open-vocabulary checkpoint (small YOLO-World v2, ~28 MB).
DEFAULT_WORLD_WEIGHTS = "yolov8s-worldv2.pt"
# CLIP text encoder used by YOLO-World to encode prompt words (downloaded once).
CLIP_WEIGHTS_RELATIVE = Path("weights") / "clip" / "ViT-B-32.pt"


class WorldProductDetector:
    """Thin wrapper around an Ultralytics YOLO-World open-vocabulary detector.

    Example:
        detector = WorldProductDetector()
        detector.set_prompts(["biscuit packet", "milk carton"])
        result = detector.detect(shelf_frame)
    """

    def __init__(
        self,
        model_path: Optional[str | Path] = None,
        device: Optional[str] = None,
    ) -> None:
        self.model_path = Path(model_path) if model_path else self._default_model_path()
        self.device = device or self._auto_device()
        self._model: Any = None
        self._names: Dict[int, str] = {}
        self._prompts: List[str] = []
        self.load()

    # ------------------------------------------------------------------
    # Paths & device
    # ------------------------------------------------------------------
    @staticmethod
    def _project_root() -> Path:
        # backend/app/services/vision/world_detector.py -> project root
        return Path(__file__).resolve().parent.parent.parent.parent.parent

    @staticmethod
    def _default_model_path() -> Path:
        return (
            WorldProductDetector._project_root()
            / "models"
            / "shelf"
            / DEFAULT_WORLD_WEIGHTS
        )

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
        from ultralytics import YOLOWorld

        local = self.model_path
        try:
            if local.exists() and local.stat().st_size > 0:
                self._model = YOLOWorld(str(local))
            else:
                # Ultralytics resolves/downloads the checkpoint by name into its
                # cache. We never fabricate model weights.
                logger.info(
                    "World weights %s not found at %s; using Ultralytics default",
                    DEFAULT_WORLD_WEIGHTS,
                    local,
                )
                self._model = YOLOWorld(DEFAULT_WORLD_WEIGHTS)
            self._names = {
                int(k): str(v) for k, v in dict(self._model.names).items()
            }
            logger.info(
                "Loaded %s | task=%s | device=%s | prompts=%d",
                local.name,
                getattr(self._model, "task", "detect"),
                self.device,
                len(self._prompts),
            )
        except Exception as exc:  # pragma: no cover - depends on host weights
            raise RuntimeError(
                f"Failed to load YOLO-World weights ({local} or "
                f"{DEFAULT_WORLD_WEIGHTS}): {exc}"
            ) from exc

    @property
    def class_names(self) -> Dict[int, str]:
        return dict(self._names)

    @property
    def prompts(self) -> List[str]:
        return list(self._prompts)

    def set_prompts(self, prompts: Optional[List[str]]) -> None:
        """Set the open-vocabulary categories to look for.

        Empty prompts mean "look for nothing" — `detect` then returns no
        detections rather than falling back to an unlisted vocabulary.
        """
        clean = _clean_prompts(prompts)
        if not clean:
            self._prompts = []
            return
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load() first.")
        # Ultralytics YOLO-World encodes the text prompts with the CLIP text
        # encoder and installs the resulting embeddings into the model.
        self._model.set_classes(clean)
        self._prompts = clean
        self._names = {
            int(k): str(v) for k, v in dict(self._model.names).items()
        }

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------
    def detect(
        self, frame: Any, conf: float = 0.25, iou: float = 0.5
    ) -> DetectionResult:
        """Run open-vocabulary detection on one BGR frame."""
        import numpy as np

        if frame is None or not hasattr(frame, "shape"):
            return DetectionResult(img_shape=[0, 0])
        h, w = frame.shape[:2]
        if not self._prompts:
            return DetectionResult(img_shape=[h, w])
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        results = self._model.predict(
            source=frame,
            device=self.device,
            imgsz=640,
            conf=conf,
            iou=iou,
            verbose=False,
        )
        return self._parse_results(results, frame_h=h, frame_w=w)

    def _parse_results(
        self, results: Any, frame_h: int, frame_w: int
    ) -> DetectionResult:
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
            cname = str(
                names.get(cid_int, self._names.get(cid_int, f"class_{cid_int}"))
            )
            result.detections.append(
                Detection(
                    class_id=cid_int,
                    class_name=cname,
                    confidence=float(conf),
                    bbox_xyxy=[float(x1), float(y1), float(x2), float(y2)],
                )
            )
        return result


def _clean_prompts(prompts: Optional[List[str]]) -> List[str]:
    """Strip and de-duplicate (case-insensitive, order-preserving) prompts."""
    if not prompts or not isinstance(prompts, (list, tuple)):
        return []
    seen = set()
    out: List[str] = []
    for raw in prompts:
        text = str(raw or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out
