"""Person detection + tracking model adapter.

Wraps the existing Vision PersonTracker (YOLO11n + ByteTrack) behind a small
interface so the pipeline never depends on Ultralytics internals. Provides a
FakePersonTracker for unit tests.

Each tracker instance carries its OWN ByteTrack state (per camera), so track
ids are never shared between cameras.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger("storeye.edge.models.person")


@dataclass
class PersonFrameResult:
    track_id: int
    confidence: float
    bbox_xyxy: List[float]


class PersonTrackerModel:
    """Real YOLO11n + ByteTrack adapter (one instance per camera)."""

    def __init__(self, model_path: Optional[str] = None, conf: Optional[float] = None):
        from app.services.vision.tracker import PersonTracker

        self.conf = conf
        self._tracker = PersonTracker(model_path=model_path)
        self._frame_index = 0

    @property
    def initialized(self) -> bool:
        return self._tracker._model is not None

    def track_frame(self, frame) -> List[PersonFrameResult]:
        """Track people in one BGR frame, returning normalized results."""
        tracking = self._tracker.track_frame(frame, frame_index=self._frame_index)
        self._frame_index += 1
        results: List[PersonFrameResult] = []
        for p in tracking.people:
            if p.track_id < 0:
                continue  # untracked boxes are not stable -> skip by default
            results.append(
                PersonFrameResult(
                    track_id=p.track_id,
                    confidence=p.confidence,
                    bbox_xyxy=list(p.bbox_xyxy),
                )
            )
        return results


class FakePersonTracker:
    """Deterministic fake tracker for unit tests / demos.

    Assigns a stable track id to a fixed set of synthetic boxes so the whole
    pipeline (throttling, observation writing, streaming) is testable without
    loading YOLO.
    """

    def __init__(self, conf: Optional[float] = None):
        self.conf = conf or 0.9
        self.reset()

    def reset(self) -> None:
        self._next_id = 1
        self._frame = 0

    @property
    def initialized(self) -> bool:
        return True

    def track_frame(self, frame) -> List[PersonFrameResult]:
        self._frame += 1
        # Emit an id that persists across frames for a simulated person.
        results = [
            PersonFrameResult(
                track_id=1,
                confidence=self.conf,
                bbox_xyxy=[10.0, 10.0, 60.0, 120.0],
            )
        ]
        # Introduce a second person after some frames to exercise tracking state.
        if self._frame >= 3:
            results.append(
                PersonFrameResult(
                    track_id=2,
                    confidence=self.conf,
                    bbox_xyxy=[80.0, 20.0, 130.0, 140.0],
                )
            )
        return results
