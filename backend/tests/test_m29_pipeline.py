"""M29 — cascaded pipeline tests (no DB): stable-track filter, selective
Re-ID accounting, person-cache wiring, ScheduleProfiler, and the durable
person-persistence flag on the ObservationWriter.

All model state is faked (FakePersonTracker + StubReIDProvider) so these are
deterministic, CI-friendly unit tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import numpy as np
import pytest

from app.edge.config import PipelineConfig
from app.edge.events import EventKind
from app.edge.frame import CameraFrame
from app.edge.models.person_detector import FakePersonTracker
from app.edge.observation_writer import ObservationWriter
from app.edge.person_cache import PersonStateManager
from app.edge.pipeline import EdgePipeline
from app.edge.workers import StageProfiler
from app.services.journeys import GlobalIdentityManager, ReIDConfig
from app.services.journeys.reid.providers import StubReIDProvider

pytestmark = [pytest.mark.no_db]

STUB = StubReIDProvider()


def make_frame(idx: int = 0, at: datetime | None = None) -> CameraFrame:
    img = np.zeros((144, 192, 3), dtype=np.uint8)
    img[:] = (30 + idx, 40, 50)
    return CameraFrame(
        camera_id="c1",
        frame_index=idx,
        timestamp=at or (datetime(2026, 9, 18, 9, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=idx)),
        image=img,
        width=192,
        height=144,
        fps=10.0,
    )


def make_reid_manager(refresh_seconds: float = 10.0) -> GlobalIdentityManager:
    manager = GlobalIdentityManager(
        config=ReIDConfig(enabled=True, provider="stub", refresh_interval_seconds=refresh_seconds),
        provider=STUB,
        store_id="s1",
    )
    manager.register_camera("c1", ["c2"])
    return manager


def base_timestamp() -> datetime:
    return datetime(2026, 9, 18, 9, 0, 0, tzinfo=timezone.utc)


class SinglePersonTracker(FakePersonTracker):
    """FakePersonTracker but with exactly ONE persistent person (the stock fake
    adds a second track from frame 3 onward, which would pollute the
    accounting tests)."""

    def track_frame(self, frame):  # noqa: D102
        self._frame += 1
        from app.edge.models.person_detector import PersonFrameResult
        return [
            PersonFrameResult(
                track_id=1,
                confidence=self.conf,
                bbox_xyxy=[10.0, 10.0, 60.0, 120.0],
            )
        ]


# ---------------------------------------------------------------------------
# Stable-track filter (cascade gating)
# ---------------------------------------------------------------------------

def test_candidate_track_gets_person_event_but_no_reid_before_stable():
    """Frames 1..2 stay candidates (stable=3): person events flow (live stream)
    but the expensive Re-ID cascade (ASSOC event + zone processing) is gated."""
    pipeline = EdgePipeline(
        camera_id="c1",
        config=PipelineConfig(
            person_detection=True, inference_interval=1,
            stable_track_min_frames=3,
        ),
        person_model=SinglePersonTracker(),
        source_label="edge:file:test.mp4",
        reid_manager=make_reid_manager(),
        store_id="s1",
        person_state=PersonStateManager(),
    )
    base = base_timestamp()
    for i in (0, 1):
        events, _ = pipeline.process(make_frame(i, at=base + timedelta(seconds=i)))
        persons = [e for e in events if e.kind == EventKind.PERSON]
        assert len(persons) == 1
        assert getattr(persons[0].payload, "global_person_id", None) is None
        assert all(e.kind != EventKind.TRACK_ASSOC for e in events)

    # Third consecutive frame -> stable -> association runs.
    events, _ = pipeline.process(make_frame(2, at=base + timedelta(seconds=2)))
    assocs = [e for e in events if e.kind == EventKind.TRACK_ASSOC]
    assert len(assocs) == 1
    assert assocs[0].payload.global_person_id


def test_interrupted_candidate_never_promotes():
    """A one-frame detection is a candidate; a gap resets the counter so it is
    never promoted. Only ONE clean TRACK_ASSOC may ever be emitted per real
    person (one journey)."""
    pipeline = EdgePipeline(
        camera_id="c1",
        config=PipelineConfig(
            person_detection=True, inference_interval=1,
            stable_track_min_frames=3,
        ),
        person_model=SinglePersonTracker(),
        source_label="edge:file:test.mp4",
        reid_manager=make_reid_manager(),
        store_id="s1",
    )
    base = base_timestamp()
    events1, _ = pipeline.process(make_frame(0, at=base))               # candidate 1
    # Frame 1 has NO person -> counter decays, never promotes.
    empty_model = FakePersonTracker()
    empty_model.track_frame = lambda frame: []  # type: ignore[method-assign]
    pipeline._person = empty_model
    pipeline.process(make_frame(1, at=base + timedelta(seconds=1)))
    # Person returns -> the counter restarts from 1.
    pipeline._person = SinglePersonTracker()
    events2, _ = pipeline.process(make_frame(2, at=base + timedelta(seconds=2)))
    persons = [e for e in events2 if e.kind == EventKind.PERSON]
    assert len(persons) == 1
    assert getattr(persons[0].payload, "global_person_id", None) is None
    assert all(e.kind != EventKind.TRACK_ASSOC for e in events2)


# ---------------------------------------------------------------------------
# Selective Re-ID: skip accounting + refresh cadence
# ---------------------------------------------------------------------------

def test_selective_reid_skips_most_frames_and_refreshes_on_cadence():
    cache = PersonStateManager()
    pipeline = EdgePipeline(
        camera_id="c1",
        config=PipelineConfig(person_detection=True, inference_interval=1),
        person_model=SinglePersonTracker(),
        source_label="edge:file:test.mp4",
        reid_manager=make_reid_manager(refresh_seconds=10.0),
        store_id="s1",
        person_state=cache,
    )
    base = base_timestamp()
    # Frame 0 -> association runs (invoice counted).
    pipeline.process(make_frame(0, at=base))
    # Frames 1..3 within the 10s refresh -> embedding inference SKIPPED.
    for i in (1, 2, 3):
        events, _ = pipeline.process(make_frame(i, at=base + timedelta(seconds=i)))
        assert all(e.kind != EventKind.TRACK_ASSOC for e in events)
    stats = cache.stats()
    assert stats["reid_invocations"] == 1
    assert stats["reid_skipped"] == 3
    # 11s mark -> refresh cadence elapses -> expensive association runs ONCE
    # more, but the same person still resolves to the SAME global id: no new
    # TRACK_ASSOC event, no second journey.
    events, _ = pipeline.process(make_frame(4, at=base + timedelta(seconds=11)))
    assert all(e.kind != EventKind.TRACK_ASSOC for e in events)
    stats = cache.stats()
    assert stats["reid_invocations"] == 2
    assert cache.stats()["reid_invocations"] == 2


def test_cached_track_still_emits_person_events_every_frame():
    cache = PersonStateManager()
    pipeline = EdgePipeline(
        camera_id="c1",
        config=PipelineConfig(person_detection=True, inference_interval=1),
        person_model=SinglePersonTracker(),
        source_label="edge:file:test.mp4",
        reid_manager=make_reid_manager(refresh_seconds=30.0),
        store_id="s1",
        person_state=cache,
    )
    base = base_timestamp()
    pipeline.process(make_frame(0, at=base))
    for i in range(1, 10):
        events, _ = pipeline.process(make_frame(i, at=base + timedelta(seconds=0.2 * i)))
        assert any(e.kind == EventKind.PERSON for e in events)
    # Hot cache holds exactly one person with the resolved global id.
    snap = cache.snapshot()
    assert len(snap) == 1
    assert snap[0]["global_person_id"]
    assert snap[0]["total_detections"] == 10
    assert snap[0]["consecutive_detections"] == 10


# ---------------------------------------------------------------------------
# Stage profiler + worker pacing surface
# ---------------------------------------------------------------------------

def test_stage_profiler_p50_p95():
    prof = StageProfiler(max_samples=100)
    for i in range(1, 101):
        prof.record("inference_ms", i * 1.0)
    summary = prof.summary()["inference_ms"]
    assert summary["count"] == 100
    assert summary["min_ms"] == 1.0
    assert summary["max_ms"] == 100.0
    assert 50 <= summary["p50_ms"] <= 52
    assert 94 <= summary["p95_ms"] <= 97


def test_worker_exposes_ai_target_fps_period():
    from app.edge.config import CameraConfig, CameraKind
    from app.edge.workers import CameraWorker

    cam = CameraConfig(
        camera_id="c1", kind=CameraKind.VIDEO_FILE, source="x.mp4",
        pipelines=PipelineConfig(person_detection=True),
        ai_target_fps=4.0,
    )
    worker = CameraWorker(cam, pipeline=None, ai_target_fps=4.0)
    assert worker._ai_period == pytest.approx(0.25)
    status = worker.status()
    assert status["ai_target_fps"] == 4.0
    assert "stage_profile" in status


# ---------------------------------------------------------------------------
# Durable-person persistence flag on the writer
# ---------------------------------------------------------------------------

def _person_event():
    from app.edge.events import person_event
    return person_event(
        camera_id="00000000-0000-4000-8000-000000000001",
        frame_number=1,
        timestamp=datetime.now(timezone.utc),
        track_id=1,
        confidence=0.9,
        bbox_xyxy=[0.0, 0.0, 1.0, 1.0],
        source="edge:file:test.mp4",
    )


def test_writer_with_persistence_off_writes_no_person_rows():
    service = MagicMock()
    writer = ObservationWriter(
        MagicMock(),
        camera_id="00000000-0000-4000-8000-000000000001",
        min_gap_seconds=0.0,
        persist_person_observations=False,
    )
    writer._service = service
    assert writer.write([_person_event()]) == 0
    service.record_person_observation.assert_not_called()
    assert writer.persist_person_observations is False


def test_writer_with_persistence_on_still_records_person_rows():
    service = MagicMock()
    writer = ObservationWriter(
        MagicMock(),
        camera_id="00000000-0000-4000-8000-000000000001",
        min_gap_seconds=0.0,
    )
    writer._service = service
    assert writer.write([_person_event()]) == 1
    service.record_person_observation.assert_called_once()