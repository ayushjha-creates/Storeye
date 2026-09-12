"""Camera worker: one per camera, running capture + inference on threads.

A worker owns:
  - its CameraSource (bounded queue of recent frames),
  - its EdgePipeline + model instances (independent tracker state),
  - an ObservationWriter (throttled persistence),
  - a latest-annotated-frame slot for the live stream,
  - its own metrics.

Capture and inference run on separate threads connected by a bounded
collections.deque-style queue so slow inference drops oldest frames rather than
building an unbounded backlog (favours the latest frame).
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import List, Optional

from ..db.session import SessionLocal
from .annotator import annotate_frame
from .camera import CameraSource, EndOfStream, CameraError, create_camera_source
from .config import CameraConfig
from .events import EdgeEvent
from .pipeline import EdgePipeline
from .observation_writer import ObservationWriter

logger = logging.getLogger("storeye.edge.worker")


class FrameSlot:
    """Bounded most-recent-frame store for the stream."""

    def __init__(self, maxlen: int = 2):
        self._maxlen = maxlen
        self._frames: deque = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def push(self, frame) -> None:
        with self._lock:
            self._frames.append(frame)

    def latest(self):
        with self._lock:
            if not self._frames:
                return None
            return self._frames[-1]

    def drain(self):
        with self._lock:
            out = list(self._frames)
            self._frames.clear()
        return out


class CameraWorker:
    """Runs one camera's capture + inference pipeline on background threads."""

    def __init__(
        self,
        config: CameraConfig,
        *,
        pipeline: EdgePipeline,
        source: Optional[CameraSource] = None,
        store_id: Optional[str] = None,
        fps_cap: float = 0.0,
        queue_size: int = 4,
    ) -> None:
        self.config = config
        self.pipeline = pipeline
        self.source = source
        self.store_id = store_id
        self.fps_cap = fps_cap  # 0 => uncapped
        self.queue_size = queue_size

        self._queue: deque = deque(maxlen=queue_size)
        self._queue_lock = threading.Lock()
        self._capture_thread: Optional[threading.Thread] = None
        self._infer_thread: Optional[threading.Thread] = None
        self._capture_period: float = 0.0
        self._stop = threading.Event()
        self._lock = threading.Lock()

        self.frames_slot = FrameSlot(maxlen=2)  # annotated frames for stream
        self.latest_events: List[EdgeEvent] = []
        self.connection_ok: bool = False
        self.error: Optional[str] = None
        self.started_at: Optional[datetime] = None
        self.last_frame_at: Optional[datetime] = None
        self.last_event_at: Optional[datetime] = None
        self.frames_captured: int = 0
        self.frames_processed: int = 0
        self.frames_dropped: int = 0
        self.observations_written: int = 0
        self._fps_samples: deque = deque(maxlen=120)
        self._writer: Optional[ObservationWriter] = None
        self._writer_owned: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    @property
    def running(self) -> bool:
        return not self._stop.is_set() and self._capture_thread is not None

    def start(self) -> "CameraWorker":
        if self.running:
            return self
        self._stop.clear()
        if self.source is None:
            self.source = create_camera_source(self.config)
        self.source.open()
        self.connection_ok = True
        self.error = None
        self.started_at = datetime.now(timezone.utc)
        # Pace video-file sources at their real-time FPS so a demo video
        # behaves like a live camera (queues don't burst-drop all frames).
        self._capture_period = self._resolve_capture_period()
        self._capture_thread = threading.Thread(
            target=self._capture_loop, name=f"edge-cap-{self.config.camera_id}", daemon=True
        )
        self._infer_thread = threading.Thread(
            target=self._infer_loop, name=f"edge-infer-{self.config.camera_id}", daemon=True
        )
        self._capture_thread.start()
        self._infer_thread.start()
        logger.info("Started camera worker %s", self.config.camera_id)
        return self

    def _resolve_capture_period(self) -> float:
        if self.fps_cap and self.fps_cap > 0:
            return 1.0 / self.fps_cap
        info = getattr(self.source, "info", None)
        src_fps = getattr(info, "fps", 0.0) or 0.0
        if self.config.kind.value == "file" and src_fps > 0:
            return 1.0 / src_fps
        # Webcam/camera sources block on read() at their own rate; no pacing.
        return 0.0

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        for t in (self._capture_thread, self._infer_thread):
            if t is not None:
                t.join(timeout)
        self._capture_thread = None
        self._infer_thread = None
        if self.source is not None:
            try:
                self.source.release()
            except Exception:  # pragma: no cover - defensive
                logger.exception("Error releasing source for %s", self.config.camera_id)
        self.last_frame_at = None
        logger.info("Stopped camera worker %s", self.config.camera_id)

    def _make_writer(self) -> ObservationWriter:
        # get_session() auto-initializes the DB engine if needed, so a background
        # worker thread never hits an un-initialized SessionLocal.
        from ..db.session import get_session
        session = get_session()
        writer = ObservationWriter(
            session,
            store_id=self.store_id,
            camera_id=self.config.camera_id,
            min_gap_seconds=self.config.pipelines.min_observation_gap_seconds,
        )
        self._writer_owned = True
        return writer

    # ------------------------------------------------------------------
    # Capture thread
    # ------------------------------------------------------------------
    def _capture_loop(self) -> None:
        period = getattr(self, "_capture_period", 0.0)
        try:
            while not self._stop.is_set():
                try:
                    frame = self.source.read()
                except EndOfStream:
                    # Bounded source exhausted -> stop this camera cleanly.
                    self.error = "eof"
                    self._stop.set()
                    break
                except CameraError as exc:
                    self.connection_ok = False
                    self.error = str(exc)
                    logger.warning("Camera %s read error: %s", self.config.camera_id, exc)
                    self._stop.set()
                    break
                except Exception as exc:  # pragma: no cover - defensive
                    self.connection_ok = False
                    self.error = f"capture error: {exc}"
                    self._stop.set()
                    break

                self.frames_captured += 1
                with self._queue_lock:
                    if len(self._queue) >= self.queue_size:
                        self.frames_dropped += 1
                    self._queue.append(frame)

                if period > 0:
                    self._stop.wait(period)
        finally:
            logger.debug("Capture loop ended for %s", self.config.camera_id)

    # ------------------------------------------------------------------
    # Inference thread
    # ------------------------------------------------------------------
    def _infer_loop(self) -> None:
        settle_ticks = 0
        try:
            while True:
                frame = None
                with self._queue_lock:
                    if self._queue:
                        frame = self._queue.popleft()
                if frame is None:
                    if self._stop.is_set():
                        # Settle: allow the capture thread a moment to append any
                        # in-flight final frames before deciding the source ended.
                        with self._queue_lock:
                            if not self._queue:
                                settle_ticks += 1
                                if settle_ticks >= 20:  # ~100ms grace
                                    break
                        self._stop.wait(0.005)
                        continue
                    self._stop.wait(0.005)
                    continue
                settle_ticks = 0
                self._process_one(frame)
        finally:
            logger.debug("Inference loop ended for %s", self.config.camera_id)

    def _process_one(self, frame) -> None:
        start = time.perf_counter()
        events, _ = self.pipeline.process(frame)
        infer_ms = (time.perf_counter() - start) * 1000.0

        self.frames_processed += 1
        self.last_frame_at = frame.timestamp
        self.latest_events = events

        # Annotated frame for the stream.
        try:
            annotated = annotate_frame(frame, events)
            self.frames_slot.push(annotated)
        except Exception:  # pragma: no cover - defensive
            pass

        if events:
            self.last_event_at = frame.timestamp
            written = self._write_events(events)
            self.observations_written += written

    def _write_events(self, events):
        try:
            if self._writer is None:
                self._writer = self._make_writer()
            try:
                return self._writer.write(events)
            finally:
                # Close the writer's session so background threads never leak
                # database connections back to the pool. Only close writers this
                # worker created (tests may inject their own).
                if self._writer_owned:
                    try:
                        self._writer.close()
                    finally:
                        self._writer = None
                        self._writer_owned = False
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Observation write failed for %s: %s", self.config.camera_id, exc)
            if self._writer_owned:
                try:
                    self._writer.close()
                except Exception:
                    pass
                self._writer = None
                self._writer_owned = False
            return 0

    # ------------------------------------------------------------------
    # Metrics/status
    # ------------------------------------------------------------------
    def current_fps(self) -> float:
        # Honest average throughput: frames processed since the worker started.
        if not self.started_at:
            return 0.0
        elapsed = (datetime.now(timezone.utc) - self.started_at).total_seconds()
        if elapsed <= 0:
            return 0.0
        return round(self.frames_processed / elapsed, 2)

    def drain_stream_frames(self) -> List[object]:
        return self.frames_slot.drain()

    def status(self) -> dict:
        uptime = None
        if self.started_at:
            uptime = (datetime.now(timezone.utc) - self.started_at).total_seconds()
        return {
            "camera_id": self.config.camera_id,
            "name": self.config.name,
            "kind": self.config.kind.value,
            "running": self.running,
            "connection_ok": self.connection_ok,
            "error": self.error,
            "enabled_pipelines": {
                "person_detection": self.config.pipelines.person_detection,
                "product_detection": self.config.pipelines.product_detection,
                "ocr": self.config.pipelines.ocr,
            },
            "fps": round(self.current_fps(), 2),
            "frames_captured": self.frames_captured,
            "frames_processed": self.frames_processed,
            "frames_dropped": self.frames_dropped,
            "observations_written": self.observations_written,
            "last_frame_at": self.last_frame_at.isoformat() if self.last_frame_at else None,
            "last_event_at": self.last_event_at.isoformat() if self.last_event_at else None,
            "uptime_seconds": round(uptime, 2) if uptime is not None else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
        }
