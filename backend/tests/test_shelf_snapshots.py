"""M30 tests: periodic shelf-occupancy snapshots.

Covers:
  * pipeline cadence model (product YOLO wall-clock gate, snapshot gate,
    0 = per-frame / disabled semantics)
  * occupancy geometry + 4-state classification + occlusion gate
  * ShelfSnapshotService persistence (rows + on-disk JPEGs + retention +
    path-traversal guard)
  * API (summary / history / single / image streaming + store authz)

No fabricated numbers: every assertion uses deterministic frames/boxes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.edge.config import PipelineConfig
from app.edge.events import EventKind
from app.edge.frame import CameraFrame
from app.edge.models.person_detector import FakePersonTracker
from app.edge.models.product_detector import FakeProductDetector
from app.edge.pipeline import EdgePipeline
from app.models import Camera, ShelfSnapshot
from app.services.shelf_snapshot.shelf_snapshot_service import (
    ShelfSnapshotService,
)
from tests.conftest import bind_test_user, make_store, resolve_test_database_url

TEST_DB_URL = resolve_test_database_url()

pipeline_mark = pytest.mark.no_db
pg_mark = pytest.mark.pg


def _frame(image: np.ndarray, idx: int = 0, ts: datetime | None = None) -> CameraFrame:
    h, w = image.shape[:2]
    return CameraFrame(
        camera_id="c1",
        frame_index=idx,
        timestamp=ts or datetime.now(timezone.utc),
        image=image,
        width=w,
        height=h,
        fps=10.0,
    )


def _pipeline(
    *,
    shelf_regions=None,
    person=True,
    product=True,
    snapshots: float = 30.0,
    product_cadence: float = 30.0,
    occlusion: float = 0.15,
    fill_low: float = 0.35,
):
    cfg = PipelineConfig(
        person_detection=person,
        product_detection=product,
        shelf_snapshot_interval_seconds=snapshots,
        product_scan_interval_seconds=product_cadence,
        shelf_occlusion_overlap_fraction=occlusion,
        shelf_fill_low_fraction=fill_low,
    )
    return EdgePipeline(
        camera_id="c1",
        config=cfg,
        person_model=FakePersonTracker() if person else None,
        product_model=FakeProductDetector() if product else None,
        source_label="edge:file:test.mp4",
        shelf_regions=shelf_regions,
    )


# A 150x200 image; the fakes emit product boxes [5,5,40,70]+[60,10,100,80]
# (pixels) and a person box [10,10,60,120].
FRAME_IMG = np.zeros((200, 150, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# Pipeline: cadence model
# ---------------------------------------------------------------------------
@pytest.mark.no_db
def test_snapshot_disabled_when_interval_zero():
    pipe = _pipeline(
        snapshots=0.0,
        shelf_regions=[{"code": "S1", "bbox": [0, 0, 50, 200]}],
    )
    events, _ = pipe.process(_frame(FRAME_IMG, 0))
    kinds = {e.kind for e in events}
    assert EventKind.SHELF_SNAPSHOT not in kinds
    # Product detection still default (30s) on the due first frame.
    assert EventKind.PRODUCT in kinds


@pytest.mark.no_db
def test_product_cadence_zero_is_per_frame():
    pipe = _pipeline(snapshots=0.0, product_cadence=0.0)
    base = datetime.now(timezone.utc)
    for i in range(3):
        events, _ = pipe.process(_frame(FRAME_IMG, i, base + timedelta(seconds=i)))
        assert any(e.kind == EventKind.PRODUCT for e in events)


@pytest.mark.no_db
def test_product_cadence_30s_limits_product_events():
    pipe = _pipeline(snapshots=0.0, product_cadence=30.0)
    base = datetime.now(timezone.utc)
    first, _ = pipe.process(_frame(FRAME_IMG, 0, base))
    assert any(e.kind == EventKind.PRODUCT for e in first)
    second, _ = pipe.process(_frame(FRAME_IMG, 1, base + timedelta(seconds=5)))
    assert not any(e.kind == EventKind.PRODUCT for e in second)
    third, _ = pipe.process(_frame(FRAME_IMG, 2, base + timedelta(seconds=35)))
    assert any(e.kind == EventKind.PRODUCT for e in third)


@pytest.mark.no_db
def test_snapshot_cadence_uses_wall_clock():
    pipe = _pipeline(
        snapshots=10.0,
        product_cadence=0.0,
        shelf_regions=[{"code": "S1", "bbox": [0, 0, 50, 200]}],
    )
    base = datetime.now(timezone.utc)
    events, _ = pipe.process(_frame(FRAME_IMG, 0, base))
    assert sum(1 for e in events if e.kind == EventKind.SHELF_SNAPSHOT) == 1
    events, _ = pipe.process(_frame(FRAME_IMG, 1, base + timedelta(seconds=1)))
    assert not any(e.kind == EventKind.SHELF_SNAPSHOT for e in events)
    events, _ = pipe.process(_frame(FRAME_IMG, 2, base + timedelta(seconds=11)))
    assert sum(1 for e in events if e.kind == EventKind.SHELF_SNAPSHOT) == 1


@pytest.mark.no_db
def test_snapshot_reuses_frame_product_boxes_without_product_events():
    """A snapshot due but product cadence not yet due still computes fill."""
    pipe = _pipeline(
        snapshots=10.0,
        product_cadence=60.0,
        shelf_regions=[{"code": "S1", "bbox": [0, 0, 50, 200]}],
    )
    base = datetime.now(timezone.utc)
    # First frame: both gates are "unseen" -> PERSON/PRODUCT + first snapshot.
    events, _ = pipe.process(_frame(FRAME_IMG, 0, base))
    assert any(e.kind == EventKind.SHELF_SNAPSHOT for e in events)
    # 10s later the snapshot gate fires again, the product gate does not.
    events, _ = pipe.process(_frame(FRAME_IMG, 1, base + timedelta(seconds=10)))
    shelf = [e for e in events if e.kind == EventKind.SHELF_SNAPSHOT]
    assert len(shelf) == 1
    assert not any(e.kind == EventKind.PRODUCT for e in events)
    p = shelf[0].payload
    assert 20.0 <= p.fill_percentage < 35.0  # deterministic ~22.75%


# ---------------------------------------------------------------------------
# Pipeline: occupancy + statuses
# ---------------------------------------------------------------------------
@pytest.mark.no_db
def test_occupancy_statuses_and_occlusion():
    # Region A: [0,0,50,200] -> one product box (~22.75% fill, LOW) AND the
    # person largely covers it (occluded). Region B: [0,90,150,200] -> no
    # products (EMPTY) and the person only barely touches it (< occlusion).
    pipe = _pipeline(
        shelf_regions=[
            {"code": "A", "bbox": [0, 0, 50, 200]},
            {"code": "B", "bbox": [0, 90, 150, 200]},
        ],
    )
    events, _ = pipe.process(_frame(FRAME_IMG, 0))
    snaps = {
        e.payload.shelf_code: e.payload
        for e in events
        if e.kind == EventKind.SHELF_SNAPSHOT
    }
    assert set(snaps) == {"A", "B"}

    a = snaps["A"]
    assert a.occluded is True
    assert a.status == "LOW"
    assert a.product_count == 1
    assert 20.0 <= a.fill_percentage < 35.0
    assert a.occlusion_note and "Person" in a.occlusion_note

    b = snaps["B"]
    assert b.occluded is False
    assert b.status == "EMPTY"
    assert b.product_count == 0
    assert b.fill_percentage == 0.0


@pytest.mark.no_db
def test_occlusion_needs_person_pipeline():
    """Without person detection there are no person boxes -> never occluded."""
    pipe = _pipeline(
        person=False,
        shelf_regions=[{"code": "A", "bbox": [0, 0, 150, 200]}],
    )
    events, _ = pipe.process(_frame(FRAME_IMG, 0))
    snaps = [e for e in events if e.kind == EventKind.SHELF_SNAPSHOT]
    assert snaps and snaps[0].payload.occluded is False


@pytest.mark.no_db
def test_full_status_at_high_cover():
    # Region covering the first product box entirely yields ~22.75% LOW;
    # a region inside the left box only -> FULL is unreachable with the fake,
    # so verify classification boundaries directly on the tap helper instead.
    pipe = _pipeline(shelf_regions=[{"code": "S", "bbox": [0, 0, 150, 200]}])
    assert pipe._classify_fill(0.05) == "EMPTY"
    assert pipe._classify_fill(0.20) == "LOW"
    assert pipe._classify_fill(0.55) == "MEDIUM"
    assert pipe._classify_fill(0.95) == "FULL"


# ---------------------------------------------------------------------------
# Pipeline: configuration validation / edge_api forwarding
# ---------------------------------------------------------------------------
@pytest.mark.no_db
def test_pipeline_validates_m30_knobs():
    bad = PipelineConfig(shelf_fill_empty_fraction=0.5, shelf_fill_low_fraction=0.2)
    with pytest.raises(ValueError):
        bad.validate()
    ok = PipelineConfig(
        product_scan_interval_seconds=5.0,
        shelf_snapshot_interval_seconds=10.0,
        shelf_occlusion_overlap_fraction=0.2,
    )
    ok.validate()


# ---------------------------------------------------------------------------
# ShelfSnapshotService: persistence (PostgreSQL)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DB_URL)
    from app.db.base import Base

    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def session_factory(engine):
    from app.db.base import Base

    with engine.begin() as conn:
        Base.metadata.drop_all(conn)
        Base.metadata.create_all(conn)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def client(session_factory):
    def override_get_db():
        session = session_factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    from app.main import app

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _seed_store_and_camera(session_factory):
    store = make_store(session_factory, "Shelf Mart")
    bind_test_user(store.id)
    session = session_factory()
    try:
        cam = Camera(
            store_id=store.id, name="Entrance", location="front",
            camera_type="usb", is_active=True,
        )
        session.add(cam)
        session.commit()
        session.refresh(cam)
        cam_id = cam.id
    finally:
        session.close()
    return store.id, cam_id


def _write_snap(session_factory, store_id, camera_id, *, code="S1", days_ago=0,
                fill=50.0, status="MEDIUM", occluded=False, image=None):
    session = session_factory()
    try:
        svc = ShelfSnapshotService(session, root="/tmp/shelf_test", store_id=store_id)
        row = svc.write_snapshot(
            camera_id=str(camera_id),
            observed_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
            shelf_code=code,
            shelf_label=None,
            region_bbox=[0.0, 0.0, 0.5, 1.0],
            fill_percentage=fill,
            status=status,
            product_count=3,
            occluded=occluded,
            occlusion_note="Person blocking" if occluded else None,
            confidence=0.88,
            frame_image=image,
        )
        assert row.store_id == store_id
        sn = row.id
    finally:
        session.close()
    return sn


def test_service_writes_row_and_files(tmp_path, session_factory):
    store = make_store(session_factory, "Disk Mart")
    session = session_factory()
    try:
        cam = Camera(store_id=store.id, name="Cam", camera_type="usb", is_active=True)
        session.add(cam)
        session.commit()
        session.refresh(cam)
        svc = ShelfSnapshotService(session, root=tmp_path, store_id=store.id, retention_days=7.0)
        image = np.zeros((200, 150, 3), dtype=np.uint8)
        row = svc.write_snapshot(
            camera_id=str(cam.id),
            observed_at=datetime.now(timezone.utc),
            shelf_code="S1",
            shelf_label="Top shelf",
            region_bbox=[0.0, 0.0, 0.5, 1.0],
            fill_percentage=45.0,
            status="MEDIUM",
            product_count=3,
            occluded=False,
            occlusion_note=None,
            confidence=0.9,
            frame_image=image,
        )
        session.refresh(row)
        assert row.snapshot_path and row.crop_path
        assert (tmp_path / row.snapshot_path).is_file()
        assert (tmp_path / row.crop_path).is_file()
        # Paths are root-relative (never absolute).
        assert not row.snapshot_path.startswith("/")
        # resolve_file streams an existing image.
        p = svc.resolve_file(row)
        assert p == (tmp_path / row.snapshot_path).resolve()
    finally:
        session.close()


def test_service_write_without_frame_has_no_files(tmp_path, session_factory):
    store = make_store(session_factory, "Noise Mart")
    session = session_factory()
    try:
        cam = Camera(store_id=store.id, name="Cam", camera_type="usb", is_active=True)
        session.add(cam)
        session.commit()
        session.refresh(cam)
        svc = ShelfSnapshotService(session, root=tmp_path, store_id=store.id)
        row = svc.write_snapshot(
            camera_id=str(cam.id), observed_at=datetime.now(timezone.utc),
            shelf_code="S1", shelf_label=None, region_bbox=None,
            fill_percentage=0.0, status="EMPTY", product_count=0,
            occluded=False, occlusion_note=None, confidence=None,
            frame_image=None,
        )
        session.refresh(row)
        assert row.snapshot_path is None and row.crop_path is None
    finally:
        session.close()


def test_service_resolve_file_rejects_path_traversal(tmp_path, session_factory):
    store = make_store(session_factory, "Guard Mart")
    session = session_factory()
    try:
        cam = Camera(store_id=store.id, name="Cam", camera_type="usb", is_active=True)
        session.add(cam)
        session.commit()
        session.refresh(cam)
        svc = ShelfSnapshotService(session, root=tmp_path, store_id=store.id)
        from app.services.shelf_snapshot.shelf_snapshot_service import (
            SnapshotNotFoundError,
        )
        row = ShelfSnapshot(
            store_id=store.id,
            camera_id=cam.id,
            shelf_code="S1",
            fill_percentage=10.0,
            status="EMPTY",
            product_count=0,
            occluded=False,
            observed_at=datetime.now(timezone.utc),
            snapshot_path="../../etc/passwd",
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        with pytest.raises(SnapshotNotFoundError):
            svc.resolve_file(row)
    finally:
        session.close()


def test_service_purge_retention(tmp_path, session_factory):
    store = make_store(session_factory, "Sweep Mart")
    session = session_factory()
    try:
        cam = Camera(store_id=store.id, name="Cam", camera_type="usb", is_active=True)
        session.add(cam)
        session.commit()
        session.refresh(cam)
        svc = ShelfSnapshotService(session, root=tmp_path, store_id=store.id, retention_days=2.0)
        svc.write_snapshot(
            camera_id=str(cam.id), observed_at=datetime.now(timezone.utc),
            shelf_code="OLD", fill_percentage=10.0, status="LOW",
            product_count=1, occluded=False, occlusion_note=None,
            confidence=None, frame_image=np.zeros((100, 100, 3), dtype=np.uint8),
        )
        old = svc.write_snapshot(
            camera_id=str(cam.id),
            observed_at=datetime.now(timezone.utc) - timedelta(days=5),
            shelf_code="OLD", fill_percentage=5.0, status="EMPTY",
            product_count=0, occluded=False, occlusion_note=None,
            confidence=None, frame_image=np.zeros((100, 100, 3), dtype=np.uint8),
        )
        removed = svc.purge_older_than(2.0)
        assert removed >= 1
        session.flush()
        total = session.execute(
            select(ShelfSnapshot)
        ).scalars().all()
        assert all(r.id != old.id for r in total)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def test_summary_and_history_and_image(client, session_factory, tmp_path, monkeypatch):
    store_id, cam_id = _seed_store_and_camera(session_factory)
    monkeypatch.setenv("EDGERETAIL_DATA_DIR", str(tmp_path))
    from app.core.config import get_settings
    get_settings.cache_clear()
    image = np.zeros((200, 150, 3), dtype=np.uint8)

    session = session_factory()
    try:
        svc = ShelfSnapshotService(session, root=tmp_path / "shelf_snapshots", store_id=store_id)
        svc.root.mkdir(parents=True, exist_ok=True)
        snap_a = svc.write_snapshot(
            camera_id=str(cam_id), observed_at=datetime.now(timezone.utc),
            shelf_code="A", fill_percentage=80.0, status="FULL", product_count=4,
            occluded=False, occlusion_note=None, confidence=0.85,
            frame_image=image,
        )
        snap_b = svc.write_snapshot(
            camera_id=str(cam_id), observed_at=datetime.now(timezone.utc),
            shelf_code="B", fill_percentage=5.0, status="EMPTY", product_count=0,
            occluded=True, occlusion_note="Person blocking", confidence=None,
            frame_image=image,
        )
        sid_a, sid_b = snap_a.id, snap_b.id
    finally:
        session.close()

    summary = client.get(
        f"/api/shelf-snapshots/summary?store_id={store_id}&camera_id={cam_id}"
    )
    assert summary.status_code == 200
    body = summary.json()
    assert body["total_regions"] == 2
    assert {i["shelf_code"] for i in body["items"]} == {"A", "B"}
    statuses = body["status"]
    assert statuses["FULL"] == 1 and statuses["LOW"] == 0
    assert statuses["MEDIUM"] == 0 and statuses["EMPTY"] == 0
    assert statuses["OCCLUDED"] == 1  # occluded rows are never also "EMPTY"

    hist = client.get(
        f"/api/shelf-snapshots/history?store_id={store_id}&camera_id={cam_id}"
        f"&shelf_code=A&limit=5"
    )
    assert hist.status_code == 200
    assert hist.json()["total"] == 1
    assert hist.json()["items"][0]["shelf_code"] == "A"

    one = client.get(f"/api/shelf-snapshots/{sid_a}")
    assert one.status_code == 200
    assert one.json()["fill_percentage"] == 80.0

    img = client.get(f"/api/shelf-snapshots/{sid_a}/image")
    assert img.status_code == 200
    assert img.headers["content-type"] == "image/jpeg"
    assert img.content[:2] == b"\xff\xd8"

    missing = client.get(f"/api/shelf-snapshots/{sid_b}/image")
    assert missing.status_code == 200  # crop exists (frame was provided)


def test_wrong_store_is_403_and_other_store_row_is_404(client, session_factory):
    store_id, cam_id = _seed_store_and_camera(session_factory)
    other = make_store(session_factory, "Other Mart")
    other_id = other.id

    r = client.get(
        f"/api/shelf-snapshots/summary?store_id={other_id}&camera_id={cam_id}"
    )
    assert r.status_code == 403

    session = session_factory()
    try:
        other_cam = Camera(store_id=other_id, name="Oc", camera_type="usb", is_active=True)
        session.add(other_cam)
        session.commit()
        session.refresh(other_cam)
        svc = ShelfSnapshotService(session, root="/tmp/x", store_id=str(other_id))
        row = svc.write_snapshot(
            camera_id=str(other_cam.id), observed_at=datetime.now(timezone.utc),
            shelf_code="S", fill_percentage=50.0, status="MEDIUM",
            product_count=2, occluded=False, occlusion_note=None,
            confidence=None, frame_image=None,
        )
        foreign_id = row.id
    finally:
        session.close()

    r = client.get(f"/api/shelf-snapshots/{foreign_id}")
    assert r.status_code == 404


def test_image_without_file_is_404(client, session_factory):
    store_id, cam_id = _seed_store_and_camera(session_factory)
    session = session_factory()
    try:
        svc = ShelfSnapshotService(session, root="/tmp/nowhere", store_id=str(store_id))
        row = svc.write_snapshot(
            camera_id=str(cam_id), observed_at=datetime.now(timezone.utc),
            shelf_code="S", fill_percentage=50.0, status="MEDIUM",
            product_count=2, occluded=False, occlusion_note=None,
            confidence=None, frame_image=None,
        )
        sid = row.id
    finally:
        session.close()
    r = client.get(f"/api/shelf-snapshots/{sid}/image")
    assert r.status_code == 404

    r2 = client.get(f"/api/shelf-snapshots/{sid}")
    assert r2.status_code == 200


def test_summary_served_from_runtime_cache_when_wired(client, session_factory, monkeypatch):
    """M30 Layer-A: when the shared runtime is store-scoped AND its mirror has
    entries for this camera, /summary is served from the cache (fast read path)
    even though PostgreSQL currently holds no rows."""
    from app.edge.registry import set_runtime
    from app.edge.runtime import EdgeRuntime
    from app.models import ShelfSnapshot

    store_id, cam_id = _seed_store_and_camera(session_factory)
    rt = EdgeRuntime()
    rt.set_store(str(store_id))
    # Insulate other tests from the shared singleton.
    import app.edge.registry as _registry
    _previous = _registry._runtime
    set_runtime(rt)
    try:
        cache = rt.get_shelf_snapshot_cache()
        row = ShelfSnapshot(
            id=uuid4(),
            store_id=store_id,
            camera_id=cam_id,
            shelf_code="S1",
            shelf_label="Top shelf",
            region_bbox=[0.0, 0.0, 0.5, 1.0],
            snapshot_path=None,
            crop_path=None,
            fill_percentage=80.0,
            status="FULL",
            product_count=4,
            occluded=False,
            occlusion_note=None,
            confidence=0.85,
            observed_at=datetime.now(timezone.utc),
        )
        cache.put(row)

        summary = client.get(
            f"/api/shelf-snapshots/summary?store_id={store_id}&camera_id={cam_id}"
        )
        assert summary.status_code == 200
        body = summary.json()
        assert body["total_regions"] == 1
        assert body["items"][0]["shelf_code"] == "S1"
        assert body["items"][0]["status"] == "FULL"
        assert body["items"][0]["has_image"] is False
        assert body["status"]["FULL"] == 1

        # DB actually has NO rows for this camera — the cache is doing the work.
        session = session_factory()
        try:
            count = session.execute(
                select(ShelfSnapshot).where(ShelfSnapshot.camera_id == cam_id)
            ).scalars().all()
            assert len(count) == 0
        finally:
            session.close()
    finally:
        set_runtime(_previous or EdgeRuntime())