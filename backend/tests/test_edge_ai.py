"""Milestone 13 tests: Edge AI Runtime + live camera integration.

Covers (with fake/injected models for deterministic, CI-friendly runs):
  * unit: pipeline tap -> structured events (person/product/OCR/expiry) + threshold
  * unit: runtime lifecycle (add/start/stop/remove/shutdown, multi-camera, status)
  * unit: per-camera tracker state isolation
  * unit: bounded-frame queue + video-file real-time pacing (no dropped frames)
  * unit: observation throttling + FK-fallback (no DB crash)
  * pg: EdgeRuntime -> observations persisted to PostgreSQL, inventory untouched
  * pg: Edge control/live API (status / start / stop / error handling)

A single real-AI smoke test (marked `real_ai`) runs the actual YOLO11n + ByteTrack
person tap against `data/tests/tracking/test_people.mp4`.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from uuid import uuid4

import cv2
import numpy as np
import pytest

from app.edge.config import CameraConfig, CameraKind, PipelineConfig
from app.edge.events import EventKind
from app.edge.frame import CameraFrame
from app.edge.models.ocr import FakeOCR
from app.edge.models.person_detector import FakePersonTracker
from app.edge.models.product_detector import FakeProductDetector
from app.edge.observation_writer import ObservationWriter
from app.edge.pipeline import EdgePipeline
from app.edge.runtime import EdgeRuntime
from app.edge.workers import CameraWorker

pytestmark = [
    pytest.mark.no_db,
]

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TRACKING_VIDEO = os.path.join(REPO_ROOT, "data/tests/tracking/test_people.mp4")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_video(path: str, frames: int = 8, fps: float = 10.0, size=(64, 48)) -> str:
    """Write a tiny synthetic mp4 (deterministic colour frames)."""
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    try:
        for i in range(frames):
            img = np.zeros((size[1], size[0], 3), dtype=np.uint8)
            img[:] = ((i * 10) % 255, 20, 40)
            vw.write(img)
    finally:
        vw.release()
    return path


class FakeRegistry:
    """Registry returning fresh fakes; never loads real models."""

    def new_person_tracker(self):
        return FakePersonTracker()

    def get_product_detector(self):
        return FakeProductDetector()

    def new_product_detector(self, **_kwargs):
        return FakeProductDetector()

    def get_ocr(self):
        return FakeOCR()

    def loaded_model_names(self):
        return []


class CountingWriter:
    """Injected writer so lifecycle tests never touch a database."""

    def __init__(self):
        self.written = 0
        self.events = []

    def write(self, events) -> int:
        self.events.extend(events)
        writable = [e for e in events if e.kind in (EventKind.PERSON, EventKind.PRODUCT,
                                                    EventKind.TEXT, EventKind.EXPIRY_METADATA)]
        self.written += len(writable)
        return len(writable)


def frame_for(image: np.ndarray, idx: int = 0) -> CameraFrame:
    h, w = image.shape[:2]
    return CameraFrame(
        camera_id="c1",
        frame_index=idx,
        timestamp=datetime.now(timezone.utc),
        image=image,
        width=w,
        height=h,
        fps=10.0,
    )


def make_pipeline(**cfg_overrides) -> EdgePipeline:
    cfg = PipelineConfig(**cfg_overrides)
    return EdgePipeline(
        camera_id="c1",
        config=cfg,
        person_model=FakePersonTracker(),
        product_model=FakeProductDetector(),
        ocr_model=FakeOCR(),
        source_label="edge:file:test.mp4",
    )


def worker_with_fake_writer(config: CameraConfig, registry: FakeRegistry) -> CameraWorker:
    pipeline = EdgePipeline(
        camera_id=config.camera_id,
        config=config.pipelines,
        person_model=registry.new_person_tracker() if config.pipelines.person_detection else None,
        product_model=registry.get_product_detector() if config.pipelines.product_detection else None,
        ocr_model=registry.get_ocr() if config.pipelines.ocr else None,
        source_label=f"edge:{config.kind.value}:{config.source}",
    )
    worker = CameraWorker(config, pipeline=pipeline, store_id=None)
    worker._writer = CountingWriter()
    return worker


# ---------------------------------------------------------------------------
# 1. Pipeline -> events (unit)
# ---------------------------------------------------------------------------
def test_pipeline_person_and_product_events(tmp_path):
    cam = CameraConfig(camera_id="c1", kind=CameraKind.VIDEO_FILE, source="x.mp4",
                       pipelines=PipelineConfig(person_detection=True, product_detection=True))
    pipeline = make_pipeline(person_detection=True, product_detection=True, ocr=True, ocr_interval=1)
    img = np.zeros((48, 64, 3), dtype=np.uint8)
    events, _ = pipeline.process(frame_for(img, 0))
    kinds = {e.kind for e in events}
    assert EventKind.PERSON in kinds
    assert EventKind.PRODUCT in kinds
    assert EventKind.TEXT in kinds
    assert EventKind.EXPIRY_METADATA in kinds
    # Anonymous, no business mutation: events only.
    for e in events:
        assert e.camera_id == "c1"


def test_pipeline_events_carry_normalized_bbox(tmp_path):
    """M32: every person/product event carries a frame-size-independent box so
    the frontend overlay renders real (pixel) camera detections correctly."""
    pipeline = make_pipeline(person_detection=True, product_detection=True, ocr=False)
    img = np.zeros((48, 64, 3), dtype=np.uint8)
    events, _ = pipeline.process(frame_for(img, 0))
    people = [e for e in events if e.kind == EventKind.PERSON]
    products = [e for e in events if e.kind == EventKind.PRODUCT]
    assert people and products
    # Fake person box is [10, 10, 60, 120] in a 64x48 frame (y2 clamps to 1.0).
    assert people[0].payload.bbox_norm == pytest.approx(
        [10 / 64, 10 / 48, 60 / 64, 1.0]
    )
    # Fake product box is [5, 5, 40, 70] (y2 clamps to 1.0).
    assert products[0].payload.bbox_norm == pytest.approx(
        [5 / 64, 5 / 48, 40 / 64, 1.0]
    )


def test_pipeline_confidence_threshold_filters(tmp_path):
    pipe = EdgePipeline(
        camera_id="c1",
        config=PipelineConfig(person_detection=True, product_detection=False, ocr=False,
                              confidence_threshold=0.99),
        person_model=FakePersonTracker(conf=0.5),
    )
    img = np.zeros((48, 64, 3), dtype=np.uint8)
    events, _ = pipe.process(frame_for(img, 0))
    assert events == []


def test_pipeline_ocr_cadence(tmp_path):
    pipe = EdgePipeline(
        camera_id="c1",
        config=PipelineConfig(person_detection=False, product_detection=False, ocr=True, ocr_interval=3),
        ocr_model=FakeOCR(),
    )
    img = np.zeros((48, 64, 3), dtype=np.uint8)
    events1, _ = pipe.process(frame_for(img, 0))  # counter=1 -> OCR tick
    events2, _ = pipe.process(frame_for(img, 1))  # counter=2 -> no OCR
    events3, _ = pipe.process(frame_for(img, 2))  # counter=3 -> no OCR
    assert any(e.kind == EventKind.TEXT for e in events1)
    assert events2 == []
    assert events3 == []


# ---------------------------------------------------------------------------
# 2 & 3. Runtime lifecycle + per-camera tracker isolation (unit)
# ---------------------------------------------------------------------------
def test_runtime_lifecycle_and_status(tmp_path):
    vid = make_video(os.path.join(str(tmp_path), "a.mp4"), frames=40, fps=8)  # 5s
    rt = EdgeRuntime(registry=FakeRegistry())
    cfg = CameraConfig(camera_id="ca", kind=CameraKind.VIDEO_FILE, source=vid,
                       pipelines=PipelineConfig(person_detection=True, product_detection=True, ocr=False))
    rt.add_camera(cfg)
    assert rt.has_camera("ca")
    assert rt.status()["camera_count"] == 1
    assert rt.status()["active_cameras"] == 0

    worker = worker_with_fake_writer(cfg, FakeRegistry())
    rt._workers["ca"] = worker
    rt.start_camera("ca")
    time.sleep(1.2)
    st = rt.camera_status("ca")
    assert st["frames_processed"] >= 3
    assert st["frames_dropped"] == 0  # paced at source FPS -> no drops
    assert st["observations_written"] > 0
    assert rt.status()["active_cameras"] == 1  # still streaming (not yet EOF)

    rt.stop_camera("ca")
    assert not rt.get_worker("ca").running
    rt.shutdown()
    assert rt.workers() == {}


def test_add_camera_applies_global_stable_track_floor():
    """The PipelineConfig sentinel default (1 = 'follow the global floor') must
    be replaced by the >1 global threshold at add_camera time, and an explicit
    per-camera value >1 must survive unchanged."""
    from app.core.config import get_settings

    rt = EdgeRuntime(registry=FakeRegistry())
    base = CameraConfig(camera_id="st", kind=CameraKind.VIDEO_FILE, source="nope.mp4",
                        pipelines=PipelineConfig(person_detection=True))
    rt.add_camera(base)
    floor = get_settings().PERSON_STABLE_TRACK_MIN_FRAMES
    assert floor > 1  # regression guard: 1-frame blips are candidates, not visitors
    assert rt.get_worker("st").pipeline.config.stable_track_min_frames == floor

    explicit = CameraConfig(camera_id="st2", kind=CameraKind.VIDEO_FILE, source="nope.mp4",
                            pipelines=PipelineConfig(person_detection=True,
                                                     stable_track_min_frames=3))
    rt.add_camera(explicit)
    assert rt.get_worker("st2").pipeline.config.stable_track_min_frames == 3
    rt.shutdown()


def test_bounded_video_runs_to_eof_and_stops(tmp_path):
    """A short file source runs to EOF, processes every frame, then stops."""
    vid = make_video(os.path.join(str(tmp_path), "eof.mp4"), frames=4, fps=8)
    rt = EdgeRuntime(registry=FakeRegistry())
    cfg = CameraConfig(camera_id="eo", kind=CameraKind.VIDEO_FILE, source=vid,
                       pipelines=PipelineConfig(person_detection=True, product_detection=False, ocr=False))
    w = worker_with_fake_writer(cfg, FakeRegistry())
    rt.add_camera(cfg)
    rt._workers["eo"] = w
    rt.start_camera("eo")
    deadline = time.time() + 5.0
    while time.time() < deadline and w.running:
        time.sleep(0.05)
    assert not w.running  # EOF -> auto-stop, no infinite loop
    assert w.frames_captured == 4
    assert w.frames_processed == 4
    rt.shutdown()


def test_multi_camera_each_has_own_tracker(tmp_path):
    vid = make_video(os.path.join(str(tmp_path), "m.mp4"), frames=3, fps=3)
    rt = EdgeRuntime(registry=FakeRegistry())
    for cid in ("one", "two"):
        cfg = CameraConfig(camera_id=cid, kind=CameraKind.VIDEO_FILE, source=vid,
                           pipelines=PipelineConfig(person_detection=True, product_detection=False, ocr=False))
        w = worker_with_fake_writer(cfg, FakeRegistry())
        rt.add_camera(cfg)
        rt._workers[cid] = w
        w.start()
    # Each camera has an isolated pipeline/person model instance.
    p1 = rt._workers["one"].pipeline._person
    p2 = rt._workers["two"].pipeline._person
    assert p1 is not p2
    # Running both is fine.
    assert all(w.running for w in rt.workers().values())
    rt.shutdown()


def test_runtime_remove_camera(tmp_path):
    vid = make_video(os.path.join(str(tmp_path), "r.mp4"), frames=2, fps=2)
    rt = EdgeRuntime(registry=FakeRegistry())
    cfg = CameraConfig(camera_id="rc", kind=CameraKind.VIDEO_FILE, source=vid,
                       pipelines=PipelineConfig(person_detection=False, product_detection=False, ocr=False))
    w = worker_with_fake_writer(cfg, FakeRegistry())
    rt.add_camera(cfg)
    rt._workers["rc"] = w
    rt.start_camera("rc")
    rt.remove_camera("rc")
    assert not rt.has_camera("rc")


# ---------------------------------------------------------------------------
# 4. Observation throttling + FK-fallback (unit, no DB)
# ---------------------------------------------------------------------------
def test_writer_throttling_respects_gap():
    from unittest.mock import MagicMock

    from app.edge.events import person_event
    from app.edge.observation_writer import ObservationWriter

    service = MagicMock()
    writer = ObservationWriter(MagicMock(), camera_id="00000000-0000-4000-8000-000000000001",
                               min_gap_seconds=10.0)
    writer._service = service
    t0 = datetime.now(timezone.utc)
    ev1 = person_event(camera_id="c1", frame_number=0, timestamp=t0, track_id=1,
                       confidence=0.9, bbox_xyxy=[0, 0, 1, 1])
    ev2 = person_event(camera_id="c1", frame_number=1, timestamp=t0, track_id=1,
                       confidence=0.9, bbox_xyxy=[0, 0, 1, 1])
    assert writer.write([ev1]) == 1
    assert writer.write([ev2]) == 0  # same kind within gap -> throttled
    assert service.record_person_observation.call_count == 1


def test_worker_reuses_writer_across_frames_and_closes_on_stop():
    """The worker keeps ONE writer across frames (so its per-kind throttle state
    survives) and closes it only on stop. Recreating it every frame reset the
    throttle and flooded the observations table."""
    from app.edge.events import person_event

    cfg = CameraConfig(camera_id="c1", kind=CameraKind.VIDEO_FILE, source="x.mp4",
                       pipelines=PipelineConfig(person_detection=True, product_detection=False))
    worker = worker_with_fake_writer(cfg, FakeRegistry())

    writer = CountingWriter()
    writer.closed = False  # type: ignore[attr-defined]

    def _close():
        writer.closed = True  # type: ignore[attr-defined]

    writer.close = _close  # type: ignore[attr-defined]
    worker._writer = writer
    worker._writer_owned = True

    ev = person_event(camera_id="c1", frame_number=0, timestamp=datetime.now(timezone.utc),
                      track_id=1, confidence=0.9, bbox_xyxy=[0, 0, 1, 1])
    worker._write_events([ev])
    worker._write_events([ev])

    assert worker._writer is writer  # same instance retained between frames
    assert writer.written == 2
    assert writer.closed is False

    worker.stop()
    assert writer.closed is True
    assert worker._writer is None


def test_writer_fk_fallback_does_not_crash():
    """A valid-UUID camera id with no matching DB row falls back to camera_id=None."""
    from unittest.mock import MagicMock

    from app.edge.events import person_event
    from app.edge.observation_writer import ObservationWriter

    service = MagicMock()
    service.record_person_observation.side_effect = [Exception("FK violation"), None]
    writer = ObservationWriter(MagicMock(), camera_id="00000000-0000-4000-8000-000000000001",
                               min_gap_seconds=0.0)
    writer._service = service
    t0 = datetime.now(timezone.utc)
    ev = person_event(camera_id="c1", frame_number=0, timestamp=t0, track_id=1,
                      confidence=0.9, bbox_xyxy=[0, 0, 1, 1])
    assert writer.write([ev]) == 1
    assert service.record_person_observation.call_count == 2
    fallback_kwargs = service.record_person_observation.call_args[1]
    assert fallback_kwargs["camera_id"] is None


# ---------------------------------------------------------------------------
# M27 Phase 17-21: explicit health enum, capacity guardrail, supervisor
# ---------------------------------------------------------------------------
def test_camera_health_states():
    from app.edge.health import (
        camera_health,
        HEALTH_RUNNING,
        HEALTH_STARTING,
        HEALTH_ERROR,
        HEALTH_STOPPED,
        HEALTH_DISABLED,
    )

    assert camera_health(running=True, connection_ok=True, error=None) == HEALTH_RUNNING
    assert camera_health(running=True, connection_ok=False, error=None) == HEALTH_STARTING
    assert camera_health(running=True, connection_ok=True, error="eof") == HEALTH_ERROR
    assert camera_health(running=False, connection_ok=False, error=None) == HEALTH_STOPPED
    assert (
        camera_health(running=False, connection_ok=False, error=None, active=False)
        == HEALTH_DISABLED
    )


def test_camera_health_degraded_and_exhaustive_states():
    from app.edge.health import (
        ALL_HEALTH_STATES,
        camera_health,
        HEALTH_DEGRADED,
        HEALTH_RUNNING,
    )

    # Stalled source while running/connected is DEGRADED, not RUNNING.
    assert (
        camera_health(running=True, connection_ok=True, error=None, stalled=True)
        == HEALTH_DEGRADED
    )
    # A recorded error always wins over staleness.
    assert camera_health(running=True, connection_ok=True, error="eof", stalled=True) == "ERROR"
    assert (
        camera_health(running=True, connection_ok=True, error=None, stalled=False)
        == HEALTH_RUNNING
    )
    # Enum is exhaustive and stable (frontend relies on exactly these values).
    assert set(ALL_HEALTH_STATES) == {
        "RUNNING",
        "DEGRADED",
        "STARTING",
        "ERROR",
        "STOPPED",
        "DISABLED",
    }


def test_worker_status_reports_health(tmp_path):
    cfg = CameraConfig(
        camera_id="h1",
        kind=CameraKind.VIDEO_FILE,
        source=make_video(os.path.join(str(tmp_path), "h.mp4"), frames=2, fps=5),
        pipelines=PipelineConfig(person_detection=False, product_detection=False, ocr=False),
    )
    worker = worker_with_fake_writer(cfg, FakeRegistry())
    assert worker.status()["health"] == "STOPPED"
    worker.start()
    try:
        assert worker.status()["health"] == "RUNNING"
    finally:
        worker.stop()


def test_runtime_capacity_guardrail(tmp_path):
    from app.edge.runtime import CameraCapacityError

    vids = [
        make_video(os.path.join(str(tmp_path), f"cap{i}.mp4"), frames=40, fps=8)
        for i in range(2)
    ]
    rt = EdgeRuntime(registry=FakeRegistry(), max_cameras=1)
    workers = {}
    for cid, vid in zip(("c1", "c2"), vids):
        cfg = CameraConfig(
            camera_id=cid,
            kind=CameraKind.VIDEO_FILE,
            source=vid,
            pipelines=PipelineConfig(person_detection=True, product_detection=False, ocr=False),
        )
        rt.add_camera(cfg)
        w = worker_with_fake_writer(cfg, FakeRegistry())
        rt._workers[cid] = w
        workers[cid] = w
    rt.start_camera("c1")
    try:
        with pytest.raises(CameraCapacityError):
            rt.start_camera("c2")
        assert not workers["c2"].running
    finally:
        rt.shutdown()


def test_runtime_forwards_fps_cap_to_worker(tmp_path):
    vid = make_video(os.path.join(str(tmp_path), "fps.mp4"), frames=20, fps=8)
    rt = EdgeRuntime(registry=FakeRegistry())
    cfg = CameraConfig(
        camera_id="f1",
        kind=CameraKind.VIDEO_FILE,
        source=vid,
        pipelines=PipelineConfig(person_detection=False, product_detection=False, ocr=False),
        fps_cap=2.5,
    )
    rt.add_camera(cfg)
    try:
        assert rt._workers["f1"].fps_cap == 2.5
    finally:
        rt.shutdown()


def test_runtime_survives_unavailable_ocr_model(tmp_path):
    class FlakyOCRRegistry(FakeRegistry):
        def get_ocr(self):
            raise RuntimeError("OCR weights unavailable")

    vid = make_video(os.path.join(str(tmp_path), "ocrfail.mp4"), frames=20, fps=8)
    rt = EdgeRuntime(registry=FlakyOCRRegistry())
    cfg = CameraConfig(
        camera_id="o1",
        kind=CameraKind.VIDEO_FILE,
        source=vid,
        pipelines=PipelineConfig(person_detection=True, product_detection=False, ocr=True),
    )
    try:
        worker = rt.add_camera(cfg)  # must not raise
        assert cfg.pipelines.ocr is False  # status reflects reality
        assert worker.pipeline._ocr is None
        worker._writer = CountingWriter()
        rt.start_camera("o1")
        assert worker.running
    finally:
        rt.shutdown()


def test_runtime_survives_unavailable_product_model(tmp_path):
    """M32: a missing YOLO-World/CLIP model disables only the product tap."""

    class FlakyProductRegistry(FakeRegistry):
        def new_product_detector(self, **_kwargs):
            raise RuntimeError("YOLO-World weights unavailable")

    vid = make_video(os.path.join(str(tmp_path), "prodfail.mp4"), frames=20, fps=8)
    rt = EdgeRuntime(registry=FlakyProductRegistry())
    cfg = CameraConfig(
        camera_id="p1",
        kind=CameraKind.VIDEO_FILE,
        source=vid,
        pipelines=PipelineConfig(person_detection=True, product_detection=True, ocr=False),
    )
    try:
        worker = rt.add_camera(cfg)  # must not raise
        assert cfg.pipelines.product_detection is False  # status reflects reality
        assert worker.pipeline._product is None
        worker._writer = CountingWriter()
        rt.start_camera("p1")
        assert worker.running
    finally:
        rt.shutdown()


def test_runtime_supports_four_cameras_and_refuses_fifth(tmp_path):
    from app.edge.runtime import CameraCapacityError

    vid = make_video(os.path.join(str(tmp_path), "four.mp4"), frames=40, fps=8)
    rt = EdgeRuntime(registry=FakeRegistry(), max_cameras=4)
    for cid in ("c1", "c2", "c3", "c4", "c5"):
        cfg = CameraConfig(
            camera_id=cid,
            kind=CameraKind.VIDEO_FILE,
            source=vid,
            pipelines=PipelineConfig(person_detection=True, product_detection=False, ocr=False),
        )
        rt.add_camera(cfg)
        rt._workers[cid] = worker_with_fake_writer(cfg, FakeRegistry())
    try:
        for cid in ("c1", "c2", "c3", "c4"):
            rt.start_camera(cid)
        assert sum(1 for w in rt.workers().values() if w.running) == 4
        with pytest.raises(CameraCapacityError):
            rt.start_camera("c5")
    finally:
        rt.shutdown()


def test_stopping_one_camera_does_not_stop_others(tmp_path):
    vid = make_video(os.path.join(str(tmp_path), "iso.mp4"), frames=60, fps=8)
    rt = EdgeRuntime(registry=FakeRegistry())
    for cid in ("a", "b"):
        cfg = CameraConfig(
            camera_id=cid,
            kind=CameraKind.VIDEO_FILE,
            source=vid,
            pipelines=PipelineConfig(person_detection=True, product_detection=False, ocr=False),
        )
        rt.add_camera(cfg)
        rt._workers[cid] = worker_with_fake_writer(cfg, FakeRegistry())
    try:
        rt.start_camera("a")
        rt.start_camera("b")
        rt.stop_camera("a")
        assert not rt._workers["a"].running
        assert rt._workers["b"].running
    finally:
        rt.shutdown()


def test_runtime_reconcile_removes_inactive_cameras(tmp_path):
    vid = make_video(os.path.join(str(tmp_path), "rec.mp4"), frames=40, fps=8)
    rt = EdgeRuntime(registry=FakeRegistry())
    for cid in ("keep", "drop"):
        cfg = CameraConfig(
            camera_id=cid,
            kind=CameraKind.VIDEO_FILE,
            source=vid,
            pipelines=PipelineConfig(person_detection=True, product_detection=False, ocr=False),
        )
        rt.add_camera(cfg)
    try:
        removed = rt.reconcile({"keep"})
        assert removed == ["drop"]
        assert rt.has_camera("keep")
        assert not rt.has_camera("drop")
    finally:
        rt.shutdown()


# ---------------------------------------------------------------------------
# Real-AI smoke (marked) - only runs when explicitly selected
# ---------------------------------------------------------------------------
@pytest.mark.real_ai
def test_worker_mirrors_shelf_snapshot_rows_into_cache():
    """M30: a SHELF_SNAPSHOT event writes a row through the snapshot service
    AND mirrors it into the runtime's Layer-A shelf cache (PG stays
    authoritative; the cache is the fast read path)."""
    from unittest.mock import MagicMock

    from app.edge.events import ShelfSnapshotPayload, shelf_snapshot_event
    from app.edge.shelf_snapshot_cache import ShelfSnapshotCache
    from app.models import ShelfSnapshot

    cache = ShelfSnapshotCache(store_id="s1")
    service = MagicMock()
    fake_row = ShelfSnapshot(
        id=uuid4(),
        store_id="s1",
        camera_id="c1",
        shelf_code="S1",
        shelf_label="Top",
        region_bbox=[0.0, 0.0, 0.5, 1.0],
        snapshot_path="c1/20260918/000000000001_S1_full.jpg",
        crop_path="c1/20260918/000000000001_S1_crop.jpg",
        fill_percentage=45.0,
        status="MEDIUM",
        product_count=3,
        occluded=False,
        confidence=0.9,
        observed_at=datetime.now(timezone.utc),
    )
    service.write_snapshot.return_value = fake_row

    cfg = CameraConfig(camera_id="c1", kind=CameraKind.VIDEO_FILE, source="x.mp4",
                       pipelines=PipelineConfig(product_detection=True))
    worker = worker_with_fake_writer(cfg, FakeRegistry())
    worker.store_id = "s1"
    worker._snapshot_service = service
    worker.shelf_snapshot_cache = cache
    worker._make_snapshot_service = MagicMock(return_value=service)

    ev = shelf_snapshot_event(
        camera_id="c1",
        frame_number=0,
        timestamp=datetime.now(timezone.utc),
        source="edge:file:test.mp4",
        payload=ShelfSnapshotPayload(
            shelf_code="S1",
            shelf_label="Top",
            region_bbox=[0.0, 0.0, 0.5, 1.0],
            fill_percentage=45.0,
            status="MEDIUM",
            product_count=3,
            occluded=False,
            occlusion_note=None,
            confidence=0.9,
        ),
    )
    frame = frame_for(np.zeros((200, 150, 3), dtype=np.uint8), 0)
    worker.pipeline.process = MagicMock(return_value=([ev], None))  # type: ignore[method-assign]
    worker._process_one(frame)

    latest = cache.latest("s1", "c1")
    assert latest["S1"].shelf_code == "S1"
    assert latest["S1"].status == "MEDIUM"
    assert latest["S1"].has_image is True
    assert cache.get_by_id(str(fake_row.id)).fill_percentage == 45.0
    assert worker._snapshots_written == 1
    assert worker.status()["shelf_snapshot_cache"]["size"] == 1
    worker.stop()


def test_real_person_smoke(tmp_path):
    from app.edge.models.registry import ModelRegistry

    model_path = os.path.join(REPO_ROOT, "models/yolo/yolo11n.pt")
    if not os.path.exists(model_path) or not os.path.exists(TRACKING_VIDEO):
        pytest.skip("real YOLO weights or demo video not present")

    rt = EdgeRuntime(registry=ModelRegistry())
    cfg = CameraConfig(camera_id="real", kind=CameraKind.VIDEO_FILE, source=TRACKING_VIDEO,
                       pipelines=PipelineConfig(person_detection=True, product_detection=False,
                                                ocr=False, ocr_interval=30,
                                                min_observation_gap_seconds=0.0))
    rt.add_camera(cfg)
    try:
        rt.start_camera("real")
        deadline = time.time() + 20.0
        frames = 0
        while time.time() < deadline:
            st = rt.camera_status("real")
            frames = st["frames_processed"]
            if frames >= 1:
                break
            time.sleep(0.25)
        st = rt.camera_status("real")
        assert st["frames_processed"] >= 1
        assert st["connection_ok"] is True
    finally:
        rt.shutdown()
