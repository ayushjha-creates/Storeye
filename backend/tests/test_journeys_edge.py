"""M19 — edge pipeline Re-ID + zone integration and journey persistence.

Covers the live wiring (not just service seams):
  * a person frame with a stub-enabled Re-ID manager emits a TRACK_ASSOC event
    and a PERSON event carrying the anonymous global_person_id
  * foot-point zone detection emits ZONE_ENTER / ZONE_EXIT journey events
  * Re-ID disabled => pipeline behaves exactly as before (plain person events)
  * the ObservationWriter dispatches journey events to PostgreSQL journeys rows
    and enriches PERSON observation details (global id / zone / reid conf)
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.edge.events import EventKind
from app.edge.frame import CameraFrame
from app.edge.models.person_detector import FakePersonTracker
from app.edge.observation_writer import ObservationWriter
from app.edge.pipeline import EdgePipeline
from app.edge.config import PipelineConfig
from app.models import (
    Camera,
    GlobalPersonSession,
    Observation,
    PersonTrackAssociation,
    Store,
    Zone,
    ZoneVisit,
)
from app.services.journeys import GlobalIdentityManager, JourneyService, ReIDConfig
from app.services.journeys.reid.providers import StubReIDProvider

pytestmark = pytest.mark.pg

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://storeye@localhost:5433/storeye_test",
)

STUB = StubReIDProvider()


def make_reid_manager(store_id: str) -> GlobalIdentityManager:
    manager = GlobalIdentityManager(
        config=ReIDConfig(enabled=True, provider="stub"),
        provider=STUB,
        store_id=store_id,
    )
    manager.register_camera("c1", ["c2"])
    return manager


def make_frame(idx: int = 0, at: datetime | None = None) -> CameraFrame:
    img = np.zeros((144, 192, 3), dtype=np.uint8)
    img[:] = (30 + idx, 40, 50)
    return CameraFrame(
        camera_id="c1",
        frame_index=idx,
        timestamp=at or (datetime.now(timezone.utc) + timedelta(seconds=idx)),
        image=img,
        width=192,
        height=144,
        fps=10.0,
    )


def make_pipeline(
    reid_manager=None,
    camera_zones=None,
    camera_zone_id: str | None = "entrance",
) -> EdgePipeline:
    return EdgePipeline(
        camera_id="c1",
        config=PipelineConfig(person_detection=True, inference_interval=1),
        person_model=FakePersonTracker(),
        source_label="edge:file:test.mp4",
        reid_manager=reid_manager,
        store_id="store:demo:1",
        camera_zone_id=camera_zone_id,
        camera_zones=camera_zones,
    )


# ---------------------------------------------------------------------------
# Re-ID tap: TRACK_ASSOC + person event enrichment
# ---------------------------------------------------------------------------

def test_track_assoc_and_person_enrichment():
    pipeline = make_pipeline(reid_manager=make_reid_manager("store:demo:1"))
    events, _ = pipeline.process(make_frame(0))

    persons = [e for e in events if e.kind == EventKind.PERSON]
    assocs = [e for e in events if e.kind == EventKind.TRACK_ASSOC]

    assert len(persons) >= 1
    assert len(assocs) == 1  # track 1 gets its global assignment once
    gid = assocs[0].payload.global_person_id
    assert gid and isinstance(gid, str)
    assert persons[0].payload.global_person_id == gid
    assert persons[0].payload.reid_confidence == "UNKNOWN"
    assert persons[0].payload.track_id >= 1


def test_reid_disabled_keeps_plain_person_events():
    pipeline = make_pipeline(reid_manager=None)
    events, _ = pipeline.process(make_frame(0))

    persons = [e for e in events if e.kind == EventKind.PERSON]
    assert len(persons) >= 1
    assert all(e.kind != EventKind.TRACK_ASSOC for e in events)
    assert all(
        getattr(e.payload, "global_person_id", None) is None for e in persons
    )


# ---------------------------------------------------------------------------
# Zone tap: enter/exit events driven by the foot point
# ---------------------------------------------------------------------------

def test_zone_enter_then_exit_emitted():
    reid_manager = make_reid_manager("store:demo:1")
    # Foot point of the fake track is (35,120) -> (0.18, 0.83) normalized.
    zones = [{"zone_id": "billing", "bbox": [0.0, 0.5, 1.0, 1.0]}]
    pipeline = make_pipeline(reid_manager=reid_manager, camera_zones=zones)

    events, _ = pipeline.process(make_frame(0))
    enters = [e for e in events if e.kind == EventKind.ZONE_ENTER]
    assert len(enters) == 1
    assert enters[0].payload.zone_id == "billing"
    assert enters[0].payload.global_person_id is not None

    # Person walks out of the billing region into the uncovered area.
    pipeline.camera_zones = [{"zone_id": "counter", "bbox": [0.0, 0.0, 1.0, 0.4]}]
    events, _ = pipeline.process(make_frame(1))
    exits = [e for e in events if e.kind == EventKind.ZONE_EXIT]
    assert len(exits) == 1
    assert exits[0].payload.zone_id == "billing"


# ---------------------------------------------------------------------------
# Writer -> journey persistence (PostgreSQL)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DB_URL)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def session_factory(engine):
    with engine.begin() as conn:
        Base.metadata.drop_all(conn)
        Base.metadata.create_all(conn)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def session(session_factory):
    s = session_factory()
    yield s
    s.close()


def test_writer_persists_journey_events(session):
    import uuid as _uuid

    store = Store(id=_uuid.uuid4(), name="Edge Journey Store")
    zone = Zone(id=_uuid.uuid4(), store_id=store.id, name="Billing")
    cam = Camera(
        id=_uuid.uuid4(), store_id=store.id, name="C1",
        location="entrance", camera_type="usb", is_active=True,
    )
    session.add_all([store, zone, cam])
    session.commit()

    from app.edge.events import (
        person_event,
        track_assoc_event,
        zone_enter_event,
        zone_exit_event,
    )

    t0 = datetime.now(timezone.utc) - timedelta(minutes=2)

    def _pa(camera_id, track_id=1):
        return person_event(
            camera_id=str(camera_id),
            frame_number=5,
            timestamp=t0,
            track_id=track_id,
            confidence=0.9,
            bbox_xyxy=[10.0, 10.0, 60.0, 120.0],
            source="edge:file:test.mp4",
            global_person_id="g-alice",
            reid_confidence="HIGH",
            zone_id=str(zone.id),
        )

    events = [
        _pa(cam.id),
        track_assoc_event(
            camera_id=str(cam.id), frame_number=5, timestamp=t0,
            track_id=1, global_person_id="g-alice", confidence="HIGH",
            source="edge:file:test.mp4",
        ),
        zone_enter_event(
            camera_id=str(cam.id), frame_number=5, timestamp=t0,
            track_id=1, global_person_id="g-alice", zone_id=str(zone.id),
            confidence="HIGH", bbox_xyxy=[10.0, 10.0, 60.0, 120.0],
            source="edge:file:test.mp4",
        ),
    ]

    writer = ObservationWriter(
        session,
        store_id=str(store.id),
        camera_id=str(cam.id),
        min_gap_seconds=0.0,
        journey_service=JourneyService(session),
    )
    written = writer.write(events)
    assert written >= 1

    gs = session.scalar(
        select(GlobalPersonSession).where(
            GlobalPersonSession.store_id == store.id,
            GlobalPersonSession.global_person_id == "g-alice",
        )
    )
    assert gs is not None
    assert gs.camera_count == 1

    assoc = session.scalar(select(PersonTrackAssociation))
    assert assoc is not None and assoc.track_id == 1
    assert session.scalar(select(ZoneVisit)) is not None
    assert session.scalar(select(ZoneVisit)).exited_at is None  # still open

    obs = session.scalar(
        select(Observation).where(Observation.store_id == store.id)
    )
    assert obs is not None
    details = obs.details or {}
    assert details.get("global_person_id") == "g-alice"
    assert details.get("reid_confidence") == "HIGH"
    assert details.get("zone_id") == str(zone.id)

    # Closing the visit computes dwell.
    exit_event = zone_exit_event(
        camera_id=str(cam.id), frame_number=6,
        timestamp=t0 + timedelta(minutes=2),
        track_id=1, global_person_id="g-alice", zone_id=str(zone.id),
        confidence="HIGH", bbox_xyxy=[10.0, 10.0, 60.0, 120.0],
        source="edge:file:test.mp4",
    )
    writer.write([exit_event])
    visit = session.scalar(select(ZoneVisit))
    assert visit.exited_at is not None
    assert visit.dwell_seconds == pytest.approx(120.0)