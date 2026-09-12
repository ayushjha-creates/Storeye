"""ByteTrack-based anonymous person tracking for Storeye.

Responsibilities (keep minimal):
- Load YOLO11n once (reuses the Milestone 1 model weights).
- Track the COCO "person" class across video frames using ByteTrack.
- Return structured, persistent anonymous tracking IDs.

Privacy: tracking IDs are temporary, session-scoped anonymous
identifiers. NO face recognition, identity recognition, embeddings,
names, or demographic classification is performed here.

This module must NOT contain database, business, billing, messaging,
expiry/FEFO, queue, or footfall logic. It is a pure CV tracking service.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

logger = logging.getLogger("storeye.vision.tracker")

PERSON_CLASS_ID = 0

# Ultralytics ships this ByteTrack config inside the installed package.
DEFAULT_TRACKER = "bytetrack.yaml"


@dataclass
class TrackedPerson:
    """One anonymously tracked person in a single frame."""

    track_id: int
    class_id: int
    class_name: str
    confidence: float
    bbox_xyxy: List[float]  # [x1, y1, x2, y2] pixel coordinates

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        x1, y1, x2, y2 = (round(v, 1) for v in self.bbox_xyxy)
        return (
            f"TrackedPerson(id={self.track_id}, cls={self.class_name}, "
            f"conf={self.confidence:.3f}, bbox=({x1},{y1},{x2},{y2}))"
        )


@dataclass
class TrackingResult:
    """Tracking result for a single frame."""

    frame_index: int
    people: List[TrackedPerson] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.people)


class PersonTracker:
    """YOLO11n + ByteTrack person-only tracker.

    Uses the Ultralytics integrated tracking API (YOLO.track with the
    ByteTrack config). ByteTrack is a tracking algorithm, not a .pt model,
    so no separate weights file is used.

    Example:
        tracker = PersonTracker()               # auto-locates the model
        for result in tracker.track_video(path):
            print(result.frame_index, len(result.people))
    """

    def __init__(
        self,
        model_path: Optional[str | Path] = None,
        device: Optional[str] = None,
        tracker_cfg: Optional[str] = None,
        conf: float = 0.25,
        iou: float = 0.5,
    ) -> None:
        """
        Args:
            model_path: Path to YOLO11n weights. Defaults to
                <project_root>/models/yolo/yolo11n.pt.
            device: 'cpu', 'mps', 'cuda', or None to auto-select.
            tracker_cfg: ByteTrack config name/path. Defaults to the
                bytetrack.yaml shipped with the installed Ultralytics.
            conf: Detection confidence threshold.
            iou: NMS IoU threshold.
        """
        from ..vision.person_detector import PersonDetector

        self.model_path = Path(model_path) if model_path else PersonDetector._default_model_path()
        self.device = device or PersonDetector._auto_device()
        self.tracker_cfg = tracker_cfg or DEFAULT_TRACKER
        self.conf = conf
        self.iou = iou
        self._model: Any = None
        self.load()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def load(self) -> None:
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Model file not found: {self.model_path}. "
                "Expected models/yolo/yolo11n.pt (Milestone 1)."
            )
        if self.model_path.stat().st_size == 0:
            raise ValueError(f"Model file is empty (0 bytes): {self.model_path}.")
        try:
            from ultralytics import YOLO

            self._model = YOLO(str(self.model_path))
            logger.info(
                "PersonTracker loaded %s (device=%s, tracker=%s)",
                self.model_path.name,
                self.device,
                self.tracker_cfg,
            )
        except Exception as exc:  # pragma: no cover - defensive
            raise RuntimeError(
                f"Failed to load YOLO model from {self.model_path}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Single-frame tracking (persistent state inside the model)
    # ------------------------------------------------------------------
    def track_frame(self, frame: Any, frame_index: int = 0) -> TrackingResult:
        """Track people in one BGR frame. Call repeatedly, in order.

        The Ultralytics model keeps internal tracker state between
        successive calls, which is what provides ID persistence.
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        results = self._model.track(
            source=frame,
            device=self.device,
            persist=True,
            tracker=self.tracker_cfg,
            conf=self.conf,
            iou=self.iou,
            classes=[PERSON_CLASS_ID],  # person-only tracking
            verbose=False,
        )
        return self._parse_results(results, frame_index)

    def _parse_results(self, results: Any, frame_index: int) -> TrackingResult:
        result = TrackingResult(frame_index=frame_index)
        if not results:
            return result

        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return result

        names: dict = self._model.names if hasattr(self._model, "names") else {}
        xyxy = boxes.xyxy.cpu().numpy()
        confs = boxes.conf.cpu().numpy()
        ids = boxes.id.cpu().numpy() if boxes.id is not None else None
        cls_ids = boxes.cls.cpu().numpy().astype(int)

        for i, (x1, y1, x2, y2) in enumerate(xyxy):
            cid = int(cls_ids[i])
            cname = str(names.get(cid, "person"))
            fid = int(ids[i]) if ids is not None else -1
            # ByteTrack may return an ID of 0/None; skip untracked boxes
            # is a defensive choice, but we keep them as id=-1 so callers
            # can see untracked detections explicitly.
            result.people.append(
                TrackedPerson(
                    track_id=fid,
                    class_id=cid,
                    class_name=cname,
                    confidence=float(confs[i]),
                    bbox_xyxy=[float(x1), float(y1), float(x2), float(y2)],
                )
            )
        return result

    # ------------------------------------------------------------------
    # Convenience: track an entire video file
    # ------------------------------------------------------------------
    def track_video(
        self,
        video_path: str | Path,
        start_frame: int = 0,
        max_frames: Optional[int] = None,
    ) -> List[TrackingResult]:
        """Track people through a video file, frame by frame.

        Yields stable track IDs across frames for as long as each person
        is trackable. Returns the full per-frame list.
        """
        import cv2

        video_path = Path(video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Video not found: {video_path}")

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            cap.release()
            raise ValueError(f"Could not open video: {video_path}")

        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if start_frame > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        results_list: List[TrackingResult] = []
        idx = 0
        try:
            while True:
                if max_frames is not None and len(results_list) >= max_frames:
                    break
                ok, frame = cap.read()
                if not ok:
                    break
                results_list.append(self.track_frame(frame, frame_index=idx))
                idx += 1
        finally:
            cap.release()

        logger.info(
            "track_video: processed %d/%d frames of %s",
            len(results_list),
            total,
            video_path.name,
        )
        return results_list

    # ------------------------------------------------------------------
    # Annotation
    # ------------------------------------------------------------------
    def annotate(
        self, frame_bgr: Any, result: TrackingResult, color=(0, 255, 0)
    ) -> Any:
        """Draw boxes + anonymous tracking IDs. Returns a new frame."""
        import cv2

        out = frame_bgr.copy()
        for p in result.people:
            x1, y1, x2, y2 = (int(v) for v in p.bbox_xyxy)
            cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
            label = f"ID:{p.track_id} {p.class_name} {p.confidence:.2f}"
            (tw, th), _ = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
            )
            top = max(y1 - th - 8, 0)
            cv2.rectangle(out, (x1, top), (x1 + tw, top + th + 6), color, -1)
            cv2.putText(
                out,
                label,
                (x1, top + th + 3),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 0, 0),
                1,
                cv2.LINE_AA,
            )
        return out

    @staticmethod
    def track_id_stats(results: List[TrackingResult]) -> dict:
        """Small stats helper: unique IDs, max concurrent, total detections."""
        ids: set = set()
        concurrent = 0
        total = 0
        for r in results:
            seen = {p.track_id for p in r.people if p.track_id >= 0}
            ids |= seen
            concurrent = max(concurrent, len(seen))
            total += len(r.people)
        return {
            "frames": len(results),
            "unique_track_ids": len(ids),
            "max_concurrent_people": concurrent,
            "total_person_detections": total,
        }