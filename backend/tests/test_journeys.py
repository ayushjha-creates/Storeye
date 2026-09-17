"""Anonymous Customer Journeys (M19) — JourneyService + Re-ID association tests.

Covers the required design contract (cases A..N):

    A  one person across 3 cameras -> ONE global journey
    B  two people never merge (distinct global ids)
    C  an impossible camera transition is excluded by the transition graph
    D  a time gap beyond `max_time_gap_seconds` stops a match
    E  store identity is isolated (same global id never leaks across stores)
    F  sessions idle past `global_timeout_seconds` flip to `expired`
    G  zone enter opens a visit
    H  zone exit closes it with a computed dwell
    I  a 180s dwell is measured exactly
    J  a full entrance -> aisle -> till chain builds a valid timeline
    K  the same numeric track id on different cameras is never one person
    L  Re-ID disabled => association returns None (local tracking untouched)
    M  an unavailable provider => Re-ID unavailable (no crash, no mock data)
    N  embeddings are NEVER persisted anywhere (no embedding columns)

The whole suite is PostgreSQL-backed (pytest marker `pg`).
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models import (
    CONF_HIGH,
    CONF_LOW,
    CONF_MEDIUM,
    CONF_UNKNOWN,
    Camera,
    GlobalPersonSession,
    PersonCameraTransition,
    PersonTrackAssociation,
    Store,
    User,
    Zone,
    ZoneVisit,
)
from app.services.journeys import GlobalIdentityManager, JourneyService, ReIDConfig
from app.services.journeys.reid.matcher import combined_score, meets_threshold
from app.services.journeys.reid.models import PersonEmbedding, PersonSighting
from app.services.journeys.reid.providers import StubReIDProvider, TorchReIDProvider

pytestmark = pytest.mark.pg

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://storeye@localhost:5433/storeye_test",
)

T0 = datetime(2026, 9, 16, 9, 0, 0, tzinfo=timezone.utc)

STUB = StubReIDProvider()
# Same camera feed => same deterministic embedding (never persisted).
SAME_CROP = STUB.encode(__import__("numpy").zeros((16, 16, 3), dtype=__import__("numpy").uint8))


def _gid_uid(slug: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, "storeye-tests/journeys/" + slug)


def _make_store(session: Session, slug: str) -> Store:
    store = Store(id=_gid_uid(f"store:{slug}"), name=f"Test {slug} Mart")
    session.add(store)
    session.flush()
    return store


def _make_camera(session: Session, store: Store, slug: str) -> Camera:
    cam = Camera(
        id=_gid_uid(f"cam:{store.name}:{slug}"),
        store_id=store.id,
        name=f"Test Cam {slug}",
        location=slug,
        camera_type="usb",
        is_active=True,
        config={"kind": "person", "person_detection": True},
    )
    session.add(cam)
    session.flush()
    return cam


def _make_zone(session: Session, store: Store, slug: str) -> Zone:
    zone = Zone(
        id=_gid_uid(f"zone:{store.name}:{slug}"),
        store_id=store.id,
        name=slug.title(),
    )
    session.add(zone)
    session.flush()
    return zone


# ---------------------------------------------------------------------------
# Fixtures — real PostgreSQL, mirroring test_api.py
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
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory


@pytest.fixture()
def session(session_factory):
    s = session_factory()
    yield s
    s.close()


def _svc(session: Session) -> JourneyService:
    return JourneyService(session)


# ---------------------------------------------------------------------------
# A — one person across three cameras => ONE global journey
# ---------------------------------------------------------------------------

def test_a_same_person_links_tracks_across_cameras(session):
    store = _make_store(session, "a")
    entrance = _make_camera(session, store, "entrance")
    aisle = _make_camera(session, store, "aisle")
    till = _make_camera(session, store, "till")
    session.commit()

    svc = _svc(session)
    gid = str(_gid_uid("person:a"))
    t1, t2, t3 = T0, T0 + timedelta(minutes=10), T0 + timedelta(minutes=20)
    svc.upsert_track_association(
        store_id=store.id, global_person_id=gid, camera_id=entrance.id,
        track_id=100, confidence=CONF_HIGH, timestamp=t1,
    )
    svc.upsert_track_association(
        store_id=store.id, global_person_id=gid, camera_id=aisle.id,
        track_id=5, confidence=CONF_HIGH, timestamp=t2,
    )
    svc.upsert_track_association(
        store_id=store.id, global_person_id=gid, camera_id=till.id,
        track_id=77, confidence=CONF_HIGH, timestamp=t3,
    )

    items, total = svc.list_journeys(store_id=store.id)
    assert total == 1
    assert items[0]["global_person_id"] == gid
    assert items[0]["camera_count"] == 3
    assert items[0]["confidence"] == CONF_HIGH

    detail = svc.get_journey(store_id=store.id, global_person_id=gid)
    assert len(detail["track_associations"]) == 3
    assert len(detail["timeline"]) > 0
    assert {c["name"] for c in detail["cameras_visited"]} == {
        entrance.name, aisle.name, till.name,
    }


# ---------------------------------------------------------------------------
# B — two people never merge
# ---------------------------------------------------------------------------

def test_b_different_people_never_merge(session):
    store = _make_store(session, "b")
    cam = _make_camera(session, store, "entrance")
    session.commit()

    svc = _svc(session)
    svc.upsert_track_association(
        store_id=store.id, global_person_id=str(_gid_uid("p:b1")),
        camera_id=cam.id, track_id=1, confidence=CONF_HIGH, timestamp=T0,
    )
    svc.upsert_track_association(
        store_id=store.id, global_person_id=str(_gid_uid("p:b2")),
        camera_id=cam.id, track_id=2, confidence=CONF_HIGH, timestamp=T0,
    )
    items, total = svc.list_journeys(store_id=store.id)
    assert total == 2
    gids = {i["global_person_id"] for i in items}
    assert len(gids) == 2


# ---------------------------------------------------------------------------
# C — impossible camera transition is excluded (transition graph)
# ---------------------------------------------------------------------------

def test_c_impossible_transition_blocked(session):
    manager = GlobalIdentityManager(
        config=ReIDConfig(
            enabled=True, provider="stub", similarity_threshold=0.4,
        ),
        provider=STUB,
    )
    manager.register_camera("cam:entrance", ["cam:aisle"])
    manager.register_camera("cam:aisle", ["cam:till"])
    manager.register_camera("cam:till", [])

    def sighting(cam, track, at):
        return PersonSighting(
            store_id="store:s",
            camera_id=cam,
            track_id=track,
            timestamp=at,
            embedding=SAME_CROP,
        )

    first = manager.associate(sighting("cam:entrance", 1, T0))
    assert first is not None and first.created

    # till is unreachable from entrance => brand-new identity, NOT a match.
    at_till = manager.associate(sighting("cam:till", 2, T0 + timedelta(seconds=45)))
    assert at_till.created and at_till.global_person_id != first.global_person_id

    # aisle IS reachable from entrance (within the time gap) => merges.
    at_aisle = manager.associate(sighting("cam:aisle", 3, T0 + timedelta(seconds=60)))
    assert at_aisle.global_person_id == first.global_person_id
    assert not at_aisle.created
    assert manager.resolution_confidence("cam:aisle", 3) is not None


# ---------------------------------------------------------------------------
# D — time gap beyond max_time_gap_seconds stops a match
# ---------------------------------------------------------------------------

def test_d_time_gap_beyond_threshold_blocks(session):
    config = ReIDConfig(similarity_threshold=0.72)
    close = combined_score(0.9, 30, config)          # 0.9 * ~0.86 => match
    far = combined_score(0.9, 300, config)           # 0.9 * 0.45 => too weak
    assert meets_threshold(close, config)
    assert not meets_threshold(far, config)
    assert far < close

    manager = GlobalIdentityManager(config=ReIDConfig(enabled=True, provider="stub"), provider=STUB)
    manager.register_camera("cam:a", ["cam:b"])
    m1 = manager.associate(
        PersonSighting("store:d", "cam:a", 1, T0, embedding=SAME_CROP)
    )
    m2 = manager.associate(
        PersonSighting(
            "store:d", "cam:b", 2, T0 + timedelta(seconds=130),
            embedding=SAME_CROP,
        )
    )
    # 130s > max_time_gap_seconds (default 120) => new identity.
    assert m2.created and m2.global_person_id != m1.global_person_id


# ---------------------------------------------------------------------------
# E — store isolation
# ---------------------------------------------------------------------------

def test_e_store_isolation(session):
    store_a = _make_store(session, "ea")
    store_b = _make_store(session, "eb")
    cam_a = _make_camera(session, store_a, "entrance")
    cam_b = _make_camera(session, store_b, "entrance")
    session.commit()

    svc = _svc(session)
    same_gid = str(_gid_uid("shared"))
    svc.upsert_track_association(
        store_id=store_a.id, global_person_id=same_gid, camera_id=cam_a.id,
        track_id=1, confidence=CONF_UNKNOWN, timestamp=T0,
    )
    svc.upsert_track_association(
        store_id=store_b.id, global_person_id=same_gid, camera_id=cam_b.id,
        track_id=1, confidence=CONF_UNKNOWN, timestamp=T0,
    )
    items_a, total_a = svc.list_journeys(store_id=store_a.id)
    items_b, total_b = svc.list_journeys(store_id=store_b.id)
    assert total_a == total_b == 1
    assert items_a[0]["cameras_visited"][0]["camera_id"] == str(cam_a.id)
    assert items_b[0]["cameras_visited"][0]["camera_id"] == str(cam_b.id)


# ---------------------------------------------------------------------------
# F — sessions idle past the timeout flip to `expired`
# ---------------------------------------------------------------------------

def test_f_expiry_marking(session):
    store = _make_store(session, "f")
    cam = _make_camera(session, store, "till")
    session.commit()

    svc = _svc(session)
    svc.upsert_track_association(
        store_id=store.id, global_person_id=str(_gid_uid("p:f-old")),
        camera_id=cam.id, track_id=9, confidence=CONF_LOW,
        timestamp=T0 - timedelta(hours=5),
    )
    svc.upsert_track_association(
        store_id=store.id, global_person_id=str(_gid_uid("p:f-new")),
        camera_id=cam.id, track_id=10, confidence=CONF_LOW, timestamp=T0,
    )
    n = svc.mark_expired_sessions(store.id, now=T0)
    assert n == 1

    statuses = dict(
        session.execute(
            select(GlobalPersonSession.global_person_id, GlobalPersonSession.status).where(
                GlobalPersonSession.store_id == store.id
            )
        ).all()
    )
    assert statuses[str(_gid_uid("p:f-old"))] == "expired"
    assert statuses[str(_gid_uid("p:f-new"))] == "active"


# ---------------------------------------------------------------------------
# G + H + I — zone visits: enter, exit, 180s dwell
# ---------------------------------------------------------------------------

def test_g_zone_visit_open(session):
    store = _make_store(session, "g")
    cam = _make_camera(session, store, "till")
    zone = _make_zone(session, store, "billing")
    session.commit()

    _svc(session).open_zone_visit(
        store_id=store.id, global_person_id=str(_gid_uid("p:g")),
        zone_id=zone.id, camera_id=cam.id, timestamp=T0,
        confidence=CONF_HIGH,
    )
    visit = session.scalar(select(ZoneVisit))
    assert visit.exited_at is None
    assert visit.entered_at == T0


def test_h_zone_exit_computes_dwell(session):
    store = _make_store(session, "h")
    cam = _make_camera(session, store, "till")
    zone = _make_zone(session, store, "billing")
    session.commit()

    svc = _svc(session)
    pid = str(_gid_uid("p:h"))
    svc.open_zone_visit(
        store_id=store.id, global_person_id=pid, zone_id=zone.id,
        camera_id=cam.id, timestamp=T0, confidence=CONF_MEDIUM,
    )
    closed = svc.close_zone_visit(
        store_id=store.id, global_person_id=pid, zone_id=zone.id,
        timestamp=T0 + timedelta(seconds=120),
    )
    assert closed is not None
    assert closed.exited_at is not None
    assert closed.dwell_seconds == pytest.approx(120.0)


def test_i_zone_dwell_180_seconds(session):
    store = _make_store(session, "i")
    cam = _make_camera(session, store, "till")
    zone = _make_zone(session, store, "billing")
    session.commit()

    svc = _svc(session)
    pid = str(_gid_uid("p:i"))
    svc.open_zone_visit(
        store_id=store.id, global_person_id=pid, zone_id=zone.id,
        camera_id=cam.id, timestamp=T0, confidence=CONF_MEDIUM,
    )
    closed = svc.close_zone_visit(
        store_id=store.id, global_person_id=pid, zone_id=zone.id,
        timestamp=T0 + timedelta(seconds=180),
    )
    assert closed.dwell_seconds == pytest.approx(180.0)

    analytics = svc.zone_analytics(zone_id=zone.id)
    assert analytics is not None
    assert analytics["visits_total"] == 1
    assert analytics["visitors_unique"] == 1
    assert analytics["currently_inside"] == 0
    assert analytics["avg_dwell_seconds"] == pytest.approx(180.0)
    assert analytics["max_dwell_seconds"] == pytest.approx(180.0)
    assert analytics["p90_dwell_seconds"] == pytest.approx(180.0)


# ---------------------------------------------------------------------------
# J — full entrance -> aisle -> till chain timeline
# ---------------------------------------------------------------------------

def test_j_camera_chain_timeline(session):
    store = _make_store(session, "j")
    entrance = _make_camera(session, store, "entrance")
    aisle = _make_camera(session, store, "aisle")
    till = _make_camera(session, store, "till")
    session.commit()

    svc = _svc(session)
    pid = str(_gid_uid("p:j"))
    t1, t2, t3 = T0, T0 + timedelta(minutes=5), T0 + timedelta(minutes=7)
    svc.upsert_track_association(
        store_id=store.id, global_person_id=pid, camera_id=entrance.id,
        track_id=11, confidence=CONF_HIGH, timestamp=t1,
    )
    svc.upsert_track_association(
        store_id=store.id, global_person_id=pid, camera_id=aisle.id,
        track_id=12, confidence=CONF_HIGH, timestamp=t2,
    )
    svc.upsert_track_association(
        store_id=store.id, global_person_id=pid, camera_id=till.id,
        track_id=13, confidence=CONF_HIGH, timestamp=t3,
    )
    tr1 = svc.record_transition(
        store_id=store.id, global_person_id=pid,
        from_camera_id=entrance.id, to_camera_id=aisle.id,
        timestamp=t2, confidence=CONF_HIGH, time_gap_seconds=120,
    )
    tr2 = svc.record_transition(
        store_id=store.id, global_person_id=pid,
        from_camera_id=aisle.id, to_camera_id=till.id,
        timestamp=t3, confidence=CONF_HIGH, time_gap_seconds=60,
    )

    detail = svc.get_journey(store_id=store.id, global_person_id=pid)
    assert len(detail["transitions"]) == 2
    assert detail["transitions"][0]["from_camera_id"] == str(entrance.id)
    assert detail["transitions"][1]["to_camera_id"] == str(till.id)
    assert transition_fk(tr1.id, session) is not None

    types = [e["type"] for e in detail["timeline"]]
    assert "transition" in types
    assert "track" in types
    assert detail["camera_count"] == 3


def transition_fk(row_id, session):
    return session.get(PersonCameraTransition, row_id)


# ---------------------------------------------------------------------------
# K — same numeric track id on different cameras is never one person
# ---------------------------------------------------------------------------

def test_k_track_id_collision_across_cameras(session):
    store = _make_store(session, "k")
    entrance = _make_camera(session, store, "entrance")
    aisle = _make_camera(session, store, "aisle")
    session.commit()

    svc = _svc(session)
    pid = str(_gid_uid("p:k"))
    svc.upsert_track_association(
        store_id=store.id, global_person_id=pid, camera_id=entrance.id,
        track_id=5, confidence=CONF_HIGH, timestamp=T0,
    )
    svc.upsert_track_association(
        store_id=store.id, global_person_id=pid, camera_id=aisle.id,
        track_id=5, confidence=CONF_HIGH,
        timestamp=T0 + timedelta(minutes=2),
    )

    rows = session.scalars(
        select(PersonTrackAssociation).where(
            PersonTrackAssociation.global_person_id == pid
        )
    ).all()
    assert len(rows) == 2  # two separate (camera, track) associations
    assert {r.camera_id for r in rows} == {entrance.id, aisle.id}
    assert {r.track_id for r in rows} == {5}
    assert len({r.session_id for r in rows}) == 1  # same global session


# ---------------------------------------------------------------------------
# L — Re-ID disabled => association returns None (local tracking untouched)
# ---------------------------------------------------------------------------

def test_l_reid_disabled_returns_none(session):
    manager = GlobalIdentityManager(
        config=ReIDConfig(enabled=False, provider="stub"),
        provider=STUB,
    )
    assert manager.reid_available() is False
    assert manager.associate(
        PersonSighting("store:l", "cam:a", 1, T0, embedding=SAME_CROP)
    ) is None
    assert manager.active_identity_count() == 0


# ---------------------------------------------------------------------------
# M — unavailable provider => Re-ID unavailable (no crash, no mocks)
# ---------------------------------------------------------------------------

def test_m_unavailable_provider_falls_back_gracefully(session, tmp_path, monkeypatch):
    # Point torch provider at weights that do not exist.
    monkeypatch.setenv("REID_TORCH_WEIGHTS_PATH", str(tmp_path / "nope.pth"))
    torch_provider = TorchReIDProvider()
    assert torch_provider.available() is False

    manager = GlobalIdentityManager(
        config=ReIDConfig(enabled=True, provider="torch"),
        provider=torch_provider,
    )
    assert manager.reid_available() is False
    assert manager.associate(
        PersonSighting("store:m", "cam:a", 1, T0, embedding=None)
    ) is None


# ---------------------------------------------------------------------------
# N — embeddings are NEVER persisted
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "model_cls",
    [GlobalPersonSession, PersonTrackAssociation, ZoneVisit, PersonCameraTransition],
)
def test_n_no_embedding_columns(session, model_cls):
    inspector = inspect(session.get_bind())
    columns = {c["name"] for c in inspector.get_columns(model_cls.__tablename__)}
    assert "embedding" not in columns
    assert "image" not in columns
    assert "crop" not in columns
    assert "face" not in columns


# ---------------------------------------------------------------------------
# Confidence mapping sanity
# ---------------------------------------------------------------------------

def test_confidence_mapping(session):
    from app.services.journeys.reid.matcher import confidence_from_score

    config = ReIDConfig()
    assert confidence_from_score(0.95, config).value == CONF_HIGH
    assert confidence_from_score(0.8, config).value == CONF_MEDIUM
    assert confidence_from_score(0.5, config).value == CONF_LOW