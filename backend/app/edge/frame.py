"""Camera frame value object.

A single decoded frame pulled from a CameraSource. Frames carry the source
identity, sequence numbers and a timestamp so downstream pipeline stages and
observation records have full provenance without reaching into the source.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class CameraFrame:
    camera_id: str
    frame_index: int  # 0-based over the whole capture session
    timestamp: datetime
    # BGR numpy array (H, W, 3). Not serialized; kept in memory only.
    image: Any
    width: int
    height: int
    fps: float = 0.0  # source's nominal FPS, 0 if unknown
    tracking_session: Optional[str] = None  # opaque session id for tracker state

    @staticmethod
    def now() -> datetime:
        return datetime.now(timezone.utc)

    def bbox_xyxy(self) -> list:
        return [0, 0, self.width, self.height]
