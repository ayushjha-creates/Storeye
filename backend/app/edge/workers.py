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
from .events import EdgeEvent, EventKind, ShelfSnapshotPayload
from .pipeline import EdgePipeline
from .observation_writer import ObservationWriter

logger = logging.getLogger("storeye.edge.worker")

# A running, connected camera that has produced no frame for this long is
# reported as DEGRADED rather than a falsely-healthy RUNNING (M27 Phase 20).
FRAME_STALL_SECONDS = 10.0


class FrameSlot:
    """Bounded most-recent-frame store for the stream."""

    def __init__(self, maxlen: int = 2):
        self._maxlen = maxlen
        self._frames: deque = deque(maxlen=maxlen)
        self._latest_jpeg: Optional[bytes] = None
        self._last_consumer_ts: float = 0.0
        self._lock = threading.Lock()

    def touch_consumer(self) -> None:
        self._last_consumer_ts = time.time()

    def has_consumer(self, window_sec: float = 4.0) -> bool:
        return (time.time() - self._last_consumer_ts) < window_sec

    def push(self, frame) -> None:
        with self._lock:
            self._frames.append(frame)

    def push_annotated(self, frame, jpeg_bytes: Optional[bytes] = None) -> None:
        with self._lock:
            self._frames.append(frame)
            if jpeg_bytes is not None:
                self._latest_jpeg = jpeg_bytes

    def get_latest_jpeg(self) -> Optional[bytes]:
        with self._lock:
            self._last_consumer_ts = time.time()
            return self._latest_jpeg

    def latest(self):
        with self._lock:
            if not self._frames:
                return None
            return self._frames[-1]

    def drain(self):
        with self._lock:
            self._last_consumer_ts = time.time()
            out = list(self._frames)
            self._frames.clear()
        return out


class StageProfiler:
    """Per-stage latency profiler (M29) with bounded sample windows.

    Records wall-clock ms per pipeline stage and reports p50/p95/mean/count
    honestly. Never fabricates a number — an empty stage is simply absent.
    """

    def __init__(self, max_samples: int = 300):
        self._max_samples = max_samples
        self._samples: dict[str, deque] = {}
        self._lock = threading.Lock()

    def record(self, stage: str, ms: float) -> None:
        with self._lock:
            bucket = self._samples.get(stage)
            if bucket is None:
                bucket = deque(maxlen=self._max_samples)
                self._samples[stage] = bucket
            bucket.append(ms)

    @staticmethod
    def _percentile(sorted_values, p: float) -> float:
        if not sorted_values:
            return 0.0
        idx = min(len(sorted_values) - 1, int((p / 100.0) * len(sorted_values)))
        return sorted_values[idx]

    def summary(self) -> dict:
        out: dict = {}
        with self._lock:
            for stage, bucket in self._samples.items():
                if not bucket:
                    continue
                values = sorted(bucket)
                total = sum(values)
                out[stage] = {
                    "count": len(values),
                    "mean_ms": round(total / len(values), 3),
                    "p50_ms": round(self._percentile(values, 50), 3),
                    "p95_ms": round(self._percentile(values, 95), 3),
                    "min_ms": round(values[0], 3),
                    "max_ms": round(values[-1], 3),
                }
        return out

    def reset(self) -> None:
        with self._lock:
            self._samples.clear()


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
        ai_target_fps: float = 0.0,
        stream_scale: float = 0.5,
        queue_size: int = 4,
        shelf_snapshot_cache=None,
    ) -> None:
        self.config = config
        self.pipeline = pipeline
        self.source = source
        self.store_id = store_id
        self.fps_cap = fps_cap  # 0 => uncapped capture
        self.ai_target_fps = ai_target_fps  # 0 => uncapped AI processing
        # Live-preview encode scale (visualization only — inference runs at full
        # resolution). Downscaling the MJPEG output cuts encode CPU cost by
        # ~scale^2, which is what keeps several cameras streaming smoothly.
        self.stream_scale = max(0.05, min(1.0, float(stream_scale or 0.5)))
        self.queue_size = queue_size
        # M30 Layer-A hot mirror: every successful PG snapshot row is mirrored
        # here so the monitor cards / history read from memory (PG still
        # authoritative; a cache miss falls back to SQL).
        self.shelf_snapshot_cache = shelf_snapshot_cache

        self._queue: deque = deque(maxlen=queue_size)
        self._queue_lock = threading.Lock()
        self._capture_thread: Optional[threading.Thread] = None
        self._infer_thread: Optional[threading.Thread] = None
        self._capture_period: float = 0.0
        self._ai_period: float = 1.0 / ai_target_fps if ai_target_fps and ai_target_fps > 0 else 0.0
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
        self._infer_ms_ewma: Optional[float] = None
        self._profiler = StageProfiler()
        self._writer: Optional[ObservationWriter] = None
        self._writer_owned: bool = False
        self._snapshot_service = None
        self._snapshot_root = None
        self._snapshots_written: int = 0
        self._last_shelf_scan_at: Optional[datetime] = None
        # Person hot cache owner (shared across the runtime) — used only for
        # periodic TTL cleanup + read-only stats surfacing. Never per-frame.
        self.person_state = getattr(pipeline, "person_state", None)

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
        self._close_writer()
        self._close_snapshot_service()
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
        from ..services.journeys import JourneyService

        session = get_session()
        writer = ObservationWriter(
            session,
            store_id=self.store_id,
            camera_id=self.config.camera_id,
            min_gap_seconds=self.config.pipelines.min_observation_gap_seconds,
            journey_service=JourneyService(session),
            persist_person_observations=self.config.pipelines.person_observation_persistence,
        )
        self._writer_owned = True
        return writer

    def _make_snapshot_service(self):
        """Lazily build the M30 shelf-snapshot persistence (own DB session)."""
        if self._snapshot_service is not None:
            return self._snapshot_service
        from ..core.config import get_settings
        from ..db.session import get_session
        from ..services.shelf_snapshot.shelf_snapshot_service import ShelfSnapshotService

        settings = get_settings()
        self._snapshot_root = settings.SHELF_SNAPSHOT_DIR
        self._snapshot_service = ShelfSnapshotService(
            get_session(),
            root=self._snapshot_root,
            store_id=self.store_id,
            camera_id=self.config.camera_id,
            retention_days=settings.SHELF_SNAPSHOT_RETENTION_DAYS,
        )
        return self._snapshot_service

    # ------------------------------------------------------------------
    # Capture thread
    # ------------------------------------------------------------------
    def _encode_stream(self, annotated):
        """Encode the annotated frame as a preview JPEG (visualization only)."""
        from .annotator import encode_mjpeg
        return encode_mjpeg(annotated)

    def _capture_loop(self) -> None:
        period = getattr(self, "_capture_period", 0.0)
        try:
            while not self._stop.is_set():
                t_cap = time.perf_counter()
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
                self.last_frame_at = frame.timestamp

                # Push latest frame to stream slot so the live MJPEG stream runs at
                # full capture rate (~25-30 FPS) without stuttering or freezing
                # while deep AI inference runs asynchronously in the background.
                # Downscaled annotation and JPEG encoding run when a stream viewer is
                # active (or thumbnail cadence every 30 frames).
                try:
                    should_encode = (
                        self.frames_slot.has_consumer()
                        or (self.frames_captured % 30 == 1)
                    )
                    if should_encode:
                        annotated = annotate_frame(
                            frame, self.latest_events, scale=self.stream_scale
                        )
                        jpg = self._encode_stream(annotated)
                        self.frames_slot.push_annotated(annotated, jpg)
                    else:
                        self.frames_slot.push(frame)
                except Exception:
                    pass

                # Bounded queue favours the LATEST frame: `deque(maxlen=...)`
                # evicts the oldest frame when full (slow AI drops stale frames
                # instead of building an unbounded backlog).
                with self._queue_lock:
                    if len(self._queue) >= self.queue_size:
                        self.frames_dropped += 1
                    self._queue.append(frame)

                if period > 0:
                    elapsed = time.perf_counter() - t_cap
                    rem = period - elapsed
                    if rem > 0:
                        self._stop.wait(rem)
                if logger.isEnabledFor(logging.DEBUG):
                    self._profiler.record(
                        "capture_ms", (time.perf_counter() - t_cap) * 1000.0
                    )
        finally:
            logger.debug("Capture loop ended for %s", self.config.camera_id)

    # ------------------------------------------------------------------
    # Inference thread
    # ------------------------------------------------------------------
    def _infer_loop(self) -> None:
        settle_ticks = 0
        ai_period = getattr(self, "_ai_period", 0.0)
        cache_cleanup_after = 0
        try:
            while True:
                frame = None
                with self._queue_lock:
                    if self._queue:
                        frame = self._queue.pop()
                        if self._queue:
                            self.frames_dropped += len(self._queue)
                            self._queue.clear()
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

                if ai_period > 0:
                    # M29 AI FPS pacing: the expensive stages are capped at
                    # ai_target_fps. Capture keeps running unthrottled, so the
                    # live stream stays fluid; this worker simply does not
                    # process more than `ai_target_fps` frames/sec, and stale
                    # frames age out of the bounded queue while it sleeps.
                    now = time.perf_counter()
                    self._process_one(frame)
                    elapsed = time.perf_counter() - now
                    remaining = ai_period - elapsed
                    if remaining > 0:
                        self._stop.wait(remaining)
                else:
                    self._process_one(frame)

                # Periodic Layer-A housekeeping (never per-frame): evict cache
                # entries idle past the TTL every ~600 processed frames.
                if self.person_state is not None:
                    cache_cleanup_after += 1
                    if cache_cleanup_after >= 600:
                        cache_cleanup_after = 0
                        try:
                            self.person_state.cleanup()
                        except Exception:  # pragma: no cover - defensive
                            logger.exception("Person cache cleanup failed for %s", self.config.camera_id)
        finally:
            logger.debug("Inference loop ended for %s", self.config.camera_id)

    def _process_one(self, frame) -> None:
        start = time.perf_counter()
        events, _ = self.pipeline.process(frame)
        infer_ms = (time.perf_counter() - start) * 1000.0

        self.frames_processed += 1
        self.last_frame_at = frame.timestamp
        self.latest_events = getattr(self.pipeline, "last_events", events)
        # Measured inference latency (EWMA), surfaced honestly in status().
        if self._infer_ms_ewma is None:
            self._infer_ms_ewma = infer_ms
        else:
            self._infer_ms_ewma = 0.2 * infer_ms + 0.8 * self._infer_ms_ewma

        # M29 Stage profiler: record the overall wall-clock and every
        # sub-stage the pipeline surfaces (person_total, reid, product, ocr).
        self._profiler.record("pipeline_ms", infer_ms)
        for key, ms in getattr(self.pipeline, "last_stage_timings", {}).items():
            self._profiler.record(f"pipeline.{key}", float(ms))

        # Throttled diagnostics: proves where real detections surface (or not).
        # DEBUG only, every 30th processed frame, and never logs images.
        if logger.isEnabledFor(logging.DEBUG) and self.frames_processed % 30 == 1:
            person = sum(1 for e in events if e.kind == EventKind.PERSON)
            product = sum(1 for e in events if e.kind == EventKind.PRODUCT)
            tracks = sorted(
                {
                    getattr(e.payload, "track_id", None)
                    for e in events
                    if e.kind == EventKind.PERSON
                    and getattr(e.payload, "track_id", None) is not None
                }
            )
            logger.debug(
                "camera=%s frame=%s processed=%s infer_ms=%.1f events=%d person=%d "
                "product=%d tracks=%s written=%d",
                self.config.camera_id,
                getattr(frame, "frame_index", None),
                self.frames_processed,
                infer_ms,
                len(events),
                person,
                product,
                tracks,
                self.observations_written,
            )

        # Update latest events for real-time overlay annotations in the capture loop
        if events:
            self.latest_events = events

        if events:
            self.last_event_at = frame.timestamp
            written = self._write_events(events)
            self.observations_written += written
            # M30: shelf snapshots are written through their own service (DB
            # rows + on-disk JPEGs + retention sweep). They must NOT also flow
            # into the generic observations writer.
            shelf_events = [e for e in events if e.kind == EventKind.SHELF_SNAPSHOT]
            if shelf_events:
                self._last_shelf_scan_at = shelf_events[-1].timestamp
                for ev in shelf_events:
                    try:
                        payload: ShelfSnapshotPayload = ev.payload
                        region_bbox = [
                            float(v) for v in (payload.region_bbox or [])
                        ] or None
                        service = self._make_snapshot_service()
                        if service is not None:
                            row = service.write_snapshot(
                                camera_id=self.config.camera_id,
                                observed_at=ev.timestamp,
                                shelf_code=payload.shelf_code,
                                shelf_label=payload.shelf_label,
                                region_bbox=region_bbox,
                                fill_percentage=payload.fill_percentage,
                                status=payload.status,
                                product_count=payload.product_count,
                                occluded=payload.occluded,
                                occlusion_note=payload.occlusion_note,
                                confidence=payload.confidence,
                                frame_image=getattr(frame, "image", None),
                            )
                            self._snapshots_written += 1
                            # M30: mirror the authoritative PG row into the hot
                            # cache so the monitor card reads from memory.
                            if self.shelf_snapshot_cache is not None:
                                try:
                                    self.shelf_snapshot_cache.put(
                                        row, store_id=self.store_id
                                    )
                                except Exception:  # pragma: no cover - defensive
                                    logger.exception(
                                        "Shelf snapshot cache mirror failed for %s",
                                        self.config.camera_id,
                                    )
                            # Evaluate shelf fill alerts immediately so urgent restock
                            # and low occupancy alerts are generated and dispatched in real-time.
                            if self.store_id:
                                try:
                                    from ..services.alerts.alert_rules import AlertRuleEngine
                                    from uuid import UUID
                                    AlertRuleEngine(service.session).evaluate_shelf_fill(
                                        store_id=UUID(str(self.store_id)),
                                        camera_id=UUID(str(self.config.camera_id)),
                                        trigger="shelf_snapshot",
                                    )
                                except Exception:  # pragma: no cover - defensive
                                    logger.warning(
                                        "Shelf fill alert evaluation failed for %s",
                                        self.config.camera_id,
                                    )
                    except Exception as exc:  # pragma: no cover - defensive
                        logger.warning(
                            "Shelf snapshot write failed for %s: %s",
                            self.config.camera_id,
                            exc,
                        )

    def _write_events(self, events):
        # M30: shelf snapshots are handled by the snapshot service in
        # `_process_one` — never by the generic observation writer.
        keep = [e for e in events if e.kind != EventKind.SHELF_SNAPSHOT]
        if not keep:
            return 0
        try:
            if self._writer is None:
                self._writer = self._make_writer()
            t_write = time.perf_counter()
            n = self._writer.write(keep)
            self._profiler.record("write_ms", (time.perf_counter() - t_write) * 1000.0)
            return n
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Observation write failed for %s: %s", self.config.camera_id, exc)
            # Drop the poisoned writer so the next frame opens a fresh session.
            self._close_writer()
            return 0

    def _close_snapshot_service(self) -> None:
        """Close the M30 snapshot service's DB session (worker stop hygiene)."""
        service = self._snapshot_service
        self._snapshot_service = None
        if service is not None:
            session = getattr(service, "session", None)
            if session is not None:
                try:
                    session.close()
                except Exception:  # pragma: no cover - defensive
                    logger.exception(
                        "Error closing shelf snapshot service for %s",
                        self.config.camera_id,
                    )

    def _close_writer(self) -> None:
        """Close and drop this worker's writer (and its session).

        The writer is intentionally kept alive across frames so its per-kind
        throttle state (min_observation_gap_seconds) and class/product mapping
        persist. Recreating it every frame reset the throttle and flooded the
        observations table every frame. It is closed on stop() or when a write
        fails, so no DB connection outlives the worker. Only writers this worker
        created are closed; tests may inject their own writer.
        """
        writer = self._writer
        owned = self._writer_owned
        self._writer = None
        self._writer_owned = False
        if writer is not None and owned:
            try:
                writer.close()
            except Exception:  # pragma: no cover - defensive
                logger.exception("Error closing observation writer for %s", self.config.camera_id)

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

    def capture_fps(self) -> float:
        # Frames actually pulled off the source per second since start.
        if not self.started_at:
            return 0.0
        elapsed = (datetime.now(timezone.utc) - self.started_at).total_seconds()
        if elapsed <= 0:
            return 0.0
        return round(self.frames_captured / elapsed, 2)

    def drain_stream_frames(self) -> List[object]:
        return self.frames_slot.drain()

    def get_latest_jpeg(self) -> Optional[bytes]:
        return self.frames_slot.get_latest_jpeg()

    def status(self) -> dict:
        uptime = None
        if self.started_at:
            uptime = (datetime.now(timezone.utc) - self.started_at).total_seconds()
        from .health import camera_health

        stalled = False
        if self.running and self.connection_ok:
            reference = self.last_frame_at or self.started_at
            if reference is not None:
                age = (datetime.now(timezone.utc) - reference).total_seconds()
                stalled = age > FRAME_STALL_SECONDS

        out = {
            "camera_id": self.config.camera_id,
            "name": self.config.name,
            "kind": self.config.kind.value,
            "running": self.running,
            "connection_ok": self.connection_ok,
            "error": self.error,
            "health": camera_health(
                running=self.running,
                connection_ok=self.connection_ok,
                error=self.error,
                stalled=stalled,
            ),
            "enabled_pipelines": {
                "person_detection": self.config.pipelines.person_detection,
                "product_detection": self.config.pipelines.product_detection,
                "ocr": self.config.pipelines.ocr,
            },
            "fps": round(self.current_fps(), 2),
            "capture_fps": self.capture_fps(),
            "inference_fps": round(self.current_fps(), 2),
            "ai_target_fps": self.ai_target_fps,
            "inference_ms": round(self._infer_ms_ewma, 2) if self._infer_ms_ewma is not None else None,
            "last_frame_age_seconds": (
                round((datetime.now(timezone.utc) - self.last_frame_at).total_seconds(), 2)
                if self.last_frame_at
                else None
            ),
            "frames_captured": self.frames_captured,
            "frames_processed": self.frames_processed,
            "frames_dropped": self.frames_dropped,
            "observations_written": self.observations_written,
            "shelf_snapshots_written": self._snapshots_written,
            "shelf_snapshot_interval_seconds": (
                self.config.pipelines.shelf_snapshot_interval_seconds
            ),
            "last_shelf_scan_at": (
                self._last_shelf_scan_at.isoformat()
                if getattr(self, "_last_shelf_scan_at", None)
                else None
            ),
            "last_frame_at": self.last_frame_at.isoformat() if self.last_frame_at else None,
            "last_event_at": self.last_event_at.isoformat() if self.last_event_at else None,
            "uptime_seconds": round(uptime, 2) if uptime is not None else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
        }
        # M29 layer-A metrics (absent when no person pipeline / no cache).
        if self.person_state is not None:
            out["person_cache"] = self.person_state.public_stats()
        # M30 shelf-snapshot mirror metrics (absent when not wiring a cache).
        if self.shelf_snapshot_cache is not None:
            out["shelf_snapshot_cache"] = self.shelf_snapshot_cache.public_stats()
        out["stage_profile"] = self._profiler.summary()
        return out
