"""Camera source abstraction.

A CameraSource yields CameraFrame objects. Subclasses wrap the actual capture
mechanism (OpenCV video file, webcam/USB, and a reserved RTSP path). They are
made to be swapped / extended without touching the pipeline.

Contract:
    - `open()` must be callable and raise CameraError on failure.
    - `read()` returns the next CameraFrame or raises EndOfStream when a
      bounded source is exhausted (video file). Continuous sources block until
      a frame is available.
    - `release()` must release all native resources (safe to call twice).
    - Every source is context-manager friendly.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..edge.frame import CameraFrame
from .config import CameraKind

logger = logging.getLogger("storeye.edge.camera")


class CameraError(Exception):
    """Raised when a camera cannot be opened/read."""


class EndOfStream(Exception):
    """Raised when a bounded source (video file) is exhausted."""


@dataclass
class CameraInfo:
    camera_id: str
    kind: CameraKind
    width: int = 0
    height: int = 0
    fps: float = 0.0
    frame_count: int = 0  # total frames for bounded sources; 0 for continuous


class CameraSource(AbstractContextManager["CameraSource"], ABC):
    """Base class for a single camera/video input."""

    def __init__(self, camera_id: str, kind: CameraKind) -> None:
        self.camera_id = camera_id
        self.kind = kind
        self._opened = False
        self._frame_index = 0

    # -- lifecycle ---------------------------------------------------------
    @abstractmethod
    def open(self) -> None:
        """Open the source; raise CameraError on failure."""

    @abstractmethod
    def read(self) -> CameraFrame:
        """Return the next frame. Raise EndOfStream when exhausted."""

    def release(self) -> None:
        """Release native resources. Idempotent."""

    def __enter__(self) -> "CameraSource":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.release()

    # -- helpers -----------------------------------------------------------
    def _next_index(self) -> int:
        idx = self._frame_index
        self._frame_index += 1
        return idx

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)


class OpenCVSource(CameraSource):
    """OpenCV-backed source. Handles both video files and camera devices."""

    def __init__(
        self,
        camera_id: str,
        source: str | int,
        kind: CameraKind,
        fps_override: float = 0.0,
    ) -> None:
        super().__init__(camera_id, kind)
        self._source = source
        self._fps_override = fps_override
        self._cap = None
        self._info: Optional[CameraInfo] = None

    def _import_cv2(self):
        try:
            import cv2
            return cv2
        except ImportError as exc:  # pragma: no cover - defensive
            raise CameraError("OpenCV (opencv-python) is required for camera capture") from exc

    def open(self) -> None:
        cv2 = self._import_cv2()
        if isinstance(self._source, int):
            cap = cv2.VideoCapture(self._source)
        else:
            cap = cv2.VideoCapture(str(self._source))
        if cap is None or not cap.isOpened():
            if cap is not None:
                cap.release()
            raise CameraError(
                f"Could not open camera/video source {self._source!r} "
                f"(camera_id={self.camera_id})"
            )
        self._cap = cap
        self._opened = True
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = self._fps_override or float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self._info = CameraInfo(
            camera_id=self.camera_id,
            kind=self.kind,
            width=w,
            height=h,
            fps=fps,
            frame_count=count,
        )
        logger.info("Opened %s source=%s (w=%d h=%d fps=%.2f)",
                    self.kind.value, self._source, w, h, fps)

    def read(self) -> CameraFrame:
        if self._cap is None or not self._opened:
            raise CameraError(f"Camera {self.camera_id} not opened")
        cv2 = self._import_cv2()
        ok, frame = self._cap.read()
        if not ok or frame is None:
            raise EndOfStream(f"Cannot read frame from {self.camera_id}")
        h, w = frame.shape[:2]
        fps = self._info.fps if self._info else 0.0
        return CameraFrame(
            camera_id=self.camera_id,
            frame_index=self._next_index(),
            timestamp=self._now(),
            image=frame,
            width=w,
            height=h,
            fps=fps,
        )

    @property
    def info(self) -> Optional[CameraInfo]:
        return self._info

    def release(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            finally:
                self._cap = None
        self._opened = False


class VideoFileSource(OpenCVSource):
    """A bounded local video file source (MP4/AVI/...)."""

    def __init__(self, camera_id: str, path: str | Path, loop: bool = False):
        path = Path(path)
        if not path.exists():
            raise CameraError(f"Video file not found: {path}")
        super().__init__(camera_id, str(path), CameraKind.VIDEO_FILE)
        self.loop = loop

    @property
    def path(self) -> str:
        return str(self._source)

    def read(self) -> CameraFrame:
        if self._cap is None or not self._opened:
            raise CameraError(f"Camera {self.camera_id} not opened")
        cv2 = self._import_cv2()
        ok, frame = self._cap.read()
        if not ok or frame is None:
            if self.loop and self._cap is not None:
                # Rewind and continue looping seamlessly
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self._cap.read()
            if not ok or frame is None:
                raise EndOfStream(f"Cannot read frame from {self.camera_id}")
        h, w = frame.shape[:2]
        fps = self._info.fps if self._info else 0.0
        return CameraFrame(
            camera_id=self.camera_id,
            frame_index=self._next_index(),
            timestamp=self._now(),
            image=frame,
            width=w,
            height=h,
            fps=fps,
        )


class WebcamSource(OpenCVSource):
    """A live webcam/USB camera device source (default index 0)."""

    def __init__(self, camera_id: str, device_index: int = 0):
        super().__init__(camera_id, int(device_index), CameraKind.WEBCAM)


class RTSPSource(CameraSource):
    """Reserved RTSP/IP-camera source (not fully exercised in M13).

    Kept as a thin, protocol-agnostic seam so IP cameras can be added later
    without rewriting the pipeline or the runtime. The concrete implementation
    is deferred — see docs/edge-ai.md.
    """

    def __init__(self, camera_id: str, url: str):
        super().__init__(camera_id, CameraKind.RTSP)
        self.url = url

    def open(self) -> None:
        # RTSP capture would use cv2.VideoCapture(self.url). M13 ships the
        # abstraction and leaves the concrete decoder for the IP-camera
        # milestone to avoid depending on specific CCTV vendors.
        raise CameraError(
            "RTSP capture is not enabled in M13; extend RTSPSource for IP cameras."
        )

    def read(self) -> CameraFrame:
        raise EndOfStream("RTSP not enabled")


def create_camera_source(config) -> CameraSource:
    """Factory mapping a CameraConfig to a concrete CameraSource."""
    kind = config.kind
    if kind == CameraKind.VIDEO_FILE:
        loop = getattr(config, "loop", False)
        return VideoFileSource(config.camera_id, config.source, loop=loop)
    if kind == CameraKind.WEBCAM:
        return WebcamSource(config.camera_id, config.device_index or 0)
    if kind == CameraKind.RTSP:
        return RTSPSource(config.camera_id, config.source)
    raise CameraError(f"Unsupported camera kind: {kind!r}")
