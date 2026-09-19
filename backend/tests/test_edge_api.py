"""Milestone 13 tests: Edge control/live API (PostgreSQL-backed).

The Edge HTTP endpoints (status, camera list, start, stop, stream) are exercised
with the real FastAPI app + real PostgreSQL `storeye_test`, but a fake model
registry is injected into the process-wide EdgeRuntime so no real weights are
loaded and runs are deterministic.

Verifies:
  * GET /api/edge/status         -> stopped when nothing is streaming
  * GET /api/edge/cameras        -> lists DB cameras (configured, not running)
  * POST /cameras/{id}/start     -> starts a file camera, streams frames
  * POST /cameras/{id}/stop      -> stops it cleanly
  * unknown camera id            -> 404
"""

from __future__ import annotations

import os
import time

import cv2
import numpy as np
import pytest
from sqlalchemy import create_engine, select

from app.api.deps import get_db
from app.db.base import Base
from app.edge import set_runtime, EdgeRuntime
from app.edge.models import FakeOCR, FakePersonTracker, FakeProductDetector
from app.main import app
from tests.conftest import bind_test_user

pytestmark = [
    pytest.mark.pg,
]

TEST_DB_URL = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg2://storeye@localhost:5433/storeye_test")


class _FakeRegistry:
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


@pytest.fixture(scope="module")
def engine():
    eng = create_engine(TEST_DB_URL)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def db(engine):
    with engine.begin() as conn:
        Base.metadata.drop_all(conn)
        Base.metadata.create_all(conn)
    from sqlalchemy.orm import Session
    session = Session(engine)
    yield session
    session.close()


@pytest.fixture()
def client(db, tmp_path, monkeypatch):
    # Generate a tiny synthetic video for the file camera.
    path = os.path.join(str(tmp_path), "cam.mp4")
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 8, (64, 48))
    try:
        for i in range(24):
            img = np.zeros((48, 64, 3), dtype=np.uint8)
            img[:] = ((i * 10) % 255, 20, 40)
            vw.write(img)
    finally:
        vw.release()

    # Route the GLOBAL DB engine (used by the edge worker's background writer)
    # to the isolated test database so AI observations never touch production.
    # `init_engine` is once-guarded process-wide, so force it to re-bind here —
    # otherwise an earlier module's lazy init could leave the worker writing to
    # production storeye (where the test camera row does not exist).
    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
    from app.db.session import dispose_engine, init_engine
    dispose_engine()
    init_engine(TEST_DB_URL)

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    # Inject a fake-model runtime for deterministic edge runs. Re-ID is kept
    # OFF here so the embedding provider (which would lazily import torch on
    # the first person frame) never slows the 0.5s frame cadence.
    fake_rt = EdgeRuntime(registry=_FakeRegistry(), reid_enabled=False)
    set_runtime(fake_rt)

    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c
    fake_rt.shutdown()
    app.dependency_overrides.clear()
    set_runtime(EdgeRuntime())


@pytest.fixture()
def store(db):
    from app.models import Store

    s = Store(name="Edge Store", timezone="Asia/Kolkata")
    db.add(s)
    db.commit()
    db.refresh(s)
    # Authenticate HTTP calls in this module as an OWNER of this store.
    bind_test_user(s.id)
    return s


@pytest.fixture(autouse=True)
def _reset_auth_overrides():
    yield
    app.dependency_overrides.clear()


def _add_camera(db, store, config):
    from app.models import Camera

    cam = Camera(name="edge-cam", store_id=store.id, camera_type="file", is_active=True)
    cam.config = config
    db.add(cam)
    db.commit()
    db.refresh(cam)
    return cam


def _base_cfg(tmp_path, **over):
    cfg = {"kind": "file", "source": f"{tmp_path}/cam.mp4"}
    cfg.update(over)
    return cfg


def test_edge_status_stopped_and_cameras_listed(client, db, store, tmp_path):
    cam = _add_camera(db, store, _base_cfg(tmp_path))

    r = client.get("/api/edge/status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "stopped"
    assert body["camera_count"] == 0  # nothing started yet
    assert body["offline"] is True  # offline-first by design

    r = client.get("/api/edge/cameras")
    assert r.status_code == 200
    cams = r.json()
    assert any(c["camera_id"] == str(cam.id) and c["running"] is False for c in cams)


def test_edge_camera_start_stop(client, db, store, tmp_path):
    cam = _add_camera(db, store, _base_cfg(tmp_path))
    cid = str(cam.id)

    r = client.post(f"/api/edge/cameras/{cid}/start")
    assert r.status_code == 200, r.text
    assert r.json()["started"] is True
    assert r.json()["running"] is True

    # Streams frames while running.
    time.sleep(0.5)
    st = client.get(f"/api/edge/cameras/{cid}").json()
    assert st["running"] is True
    assert st["frames_processed"] >= 1

    r = client.post(f"/api/edge/cameras/{cid}/stop")
    assert r.status_code == 200
    assert r.json()["started"] is False
    assert r.json()["running"] is False

    st = client.get(f"/api/edge/cameras/{cid}").json()
    assert st["running"] is False


def test_edge_stream_returns_mjpeg_when_running(client, db, store, tmp_path):
    import threading

    cam = _add_camera(db, store, _base_cfg(tmp_path))
    client.post(f"/api/edge/cameras/{str(cam.id)}/start")

    # Stop the camera from a background thread shortly after streaming starts so
    # the (inherently infinite-while-running) MJPEG generator hits EOF and the
    # body can be fully drained in the test.
    stopper = threading.Thread(
        target=lambda: (time.sleep(0.4), client.post(f"/api/edge/cameras/{str(cam.id)}/stop")),
        daemon=True,
    )
    stopper.start()

    with client.stream("GET", f"/api/edge/cameras/{str(cam.id)}/stream") as stream:
        assert stream.status_code == 200
        assert "x-mixed-replace" in stream.headers.get("content-type", "")
        chunks = list(stream.iter_bytes(1024))
        # At least the MJPEG boundary header was produced.
        assert len(chunks) > 0

    stopper.join(timeout=5)
    assert client.get(f"/api/edge/cameras/{str(cam.id)}").json()["running"] is False


def test_edge_unknown_camera_404(client, db, store):
    r = client.post("/api/edge/cameras/00000000-0000-4000-8000-000000000000/start")
    assert r.status_code == 404
    r = client.get("/api/edge/cameras/00000000-0000-4000-8000-000000000000")
    assert r.status_code == 404


def test_edge_observations_persist_without_touching_inventory(client, db, store, tmp_path):
    from app.models import Inventory, Observation

    cam = _add_camera(db, store, {
        "kind": "file",
        "source": f"{tmp_path}/cam.mp4",
        "pipelines": {
            "person_detection": True,
            "product_detection": True,
            "ocr": True,
            "ocr_interval": 3,
            "min_observation_gap_seconds": 0.0,
        },
    })
    client.post(f"/api/edge/cameras/{str(cam.id)}/start")

    obs_count = 0
    deadline = time.time() + 10.0
    while time.time() < deadline:
        obs_count = db.query(Observation).count()
        if obs_count > 0:
            break
        time.sleep(0.1)

    client.post(f"/api/edge/cameras/{str(cam.id)}/stop")

    inv_count = db.query(Inventory).count()
    assert obs_count > 0  # AI observations were persisted
    assert inv_count == 0  # and NOTHING touched inventory


def test_config_from_camera_forwards_shelf_regions():
    """M27: manual shelf regions reach the runtime CameraConfig (no detector)."""
    from uuid import uuid4

    from app.api.edge_api import _config_from_camera
    from app.models import Camera

    cam = Camera(name="shelf-cam", store_id=uuid4(), camera_type="usb", is_active=True)
    cam.config = {
        "kind": "usb",
        "shelf_regions": [
            {"code": "A1", "label": "Chips", "bbox": [0, 0, 320, 240]},
            {"code": "A2", "bbox": [0, 240, 320, 480]},
        ],
    }
    cfg = _config_from_camera(cam)
    assert cfg.shelf_regions == [
        {"code": "A1", "label": "Chips", "bbox": [0, 0, 320, 240]},
        {"code": "A2", "bbox": [0, 240, 320, 480]},
    ]
    # M30 default shelf-occupancy knobs are forwarded from the camera config.
    assert cfg.pipelines.shelf_snapshot_interval_seconds == 30.0
    assert cfg.pipelines.product_scan_interval_seconds == 30.0


def test_config_from_camera_forwards_m30_pipeline_knobs():
    """M30: cadence + occupancy thresholds reach the runtime PipelineConfig."""
    from uuid import uuid4

    from app.api.edge_api import _config_from_camera
    from app.models import Camera

    cam = Camera(name="m30-cam", store_id=uuid4(), camera_type="usb", is_active=True)
    cam.config = {
        "kind": "usb",
        "pipelines": {
            "product_scan_interval_seconds": 5.0,
            "shelf_snapshot_interval_seconds": 7.0,
            "shelf_fill_empty_fraction": 0.08,
            "shelf_fill_low_fraction": 0.30,
            "shelf_fill_medium_fraction": 0.65,
            "shelf_occlusion_overlap_fraction": 0.25,
        },
    }
    cfg = _config_from_camera(cam)
    assert cfg.pipelines.product_scan_interval_seconds == 5.0
    assert cfg.pipelines.shelf_snapshot_interval_seconds == 7.0
    assert cfg.pipelines.shelf_fill_empty_fraction == 0.08
    assert cfg.pipelines.shelf_fill_low_fraction == 0.30
    assert cfg.pipelines.shelf_fill_medium_fraction == 0.65
    assert cfg.pipelines.shelf_occlusion_overlap_fraction == 0.25


def test_config_from_camera_stable_track_uses_global_floor():
    """M32 clean-up: an unset per-camera stable-track threshold must default to
    the global floor (>1) so single-frame detector blips never become journeys;
    an explicit per-camera value >1 still wins."""
    from uuid import uuid4

    from app.api.edge_api import _config_from_camera
    from app.core.config import get_settings
    from app.models import Camera

    floor = get_settings().PERSON_STABLE_TRACK_MIN_FRAMES
    assert floor > 1  # regression guard: one-frame tracks must stay candidates

    cam = Camera(name="stable-cam", store_id=uuid4(), camera_type="usb", is_active=True)
    cam.config = {"kind": "usb"}
    cfg = _config_from_camera(cam)
    assert cfg.pipelines.stable_track_min_frames == floor

    cam.config = {"kind": "usb", "pipelines": {"stable_track_min_frames": 3}}
    cfg = _config_from_camera(cam)
    assert cfg.pipelines.stable_track_min_frames == 3


def test_config_from_camera_forwards_product_detector_and_prompts():
    """M32: product model choice + operator prompts reach the runtime."""
    from uuid import uuid4

    from app.api.edge_api import _config_from_camera
    from app.models import Camera

    cam = Camera(name="m32-cam", store_id=uuid4(), camera_type="usb", is_active=True)
    cam.config = {
        "kind": "usb",
        "pipelines": {
            "product_detector": "shelf",
            "product_prompts": ["Biscuit", "biscuit", "Milk 1L"],
        },
    }
    cfg = _config_from_camera(cam)
    assert cfg.pipelines.product_detector == "shelf"
    assert cfg.pipelines.product_prompts == ["Biscuit", "Milk 1L"]


def test_config_from_camera_derives_prompts_from_catalog_when_unset():
    """M32: with no prompts, the vocabulary comes from the store's own catalog."""
    from uuid import uuid4

    from app.api.edge_api import _config_from_camera
    from app.models import Camera

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _DB:
        def execute(self, _stmt):
            return _Result(
                [
                    (["Complan"], "Complan", "Complan Junior"),
                    (None, "Amul", "Amul Milk 1L"),
                ]
            )

    cam = Camera(name="m32-cam", store_id=uuid4(), camera_type="usb", is_active=True)
    cam.config = {"kind": "usb"}
    cfg = _config_from_camera(cam, _DB())
    assert cfg.pipelines.product_detector == "world"
    assert "Complan" in cfg.pipelines.product_prompts
    assert "Amul Milk 1L" in cfg.pipelines.product_prompts


def test_config_from_camera_rejects_unknown_detector_value():
    from uuid import uuid4

    from app.api.edge_api import _config_from_camera
    from app.models import Camera

    cam = Camera(name="m32-cam", store_id=uuid4(), camera_type="usb", is_active=True)
    cam.config = {"kind": "usb", "pipelines": {"product_detector": "bogus"}}
    assert _config_from_camera(cam).pipelines.product_detector == "world"


def test_edge_cameras_report_explicit_health(client, db, store, tmp_path):
    """M27: the API reports one canonical health state per camera."""
    from app.models import Camera

    active = _add_camera(db, store, _base_cfg(tmp_path))
    inactive = Camera(name="off-cam", store_id=store.id, camera_type="usb", is_active=False)
    inactive.config = {"kind": "usb", "source_index": 0}
    db.add(inactive)
    db.commit()
    db.refresh(inactive)

    r = client.get("/api/edge/cameras")
    assert r.status_code == 200
    byid = {c["camera_id"]: c for c in r.json()}
    assert byid[str(active.id)]["health"] == "STOPPED"
    assert byid[str(inactive.id)]["health"] == "DISABLED"


def test_edge_status_reports_capacity(client, db, store, tmp_path):
    _add_camera(db, store, _base_cfg(tmp_path))
    body = client.get("/api/edge/status").json()
    assert isinstance(body["max_cameras"], int)
    assert body["max_cameras"] >= 0


def test_edge_start_refuses_over_capacity(client, db, store, tmp_path):
    from app.edge import get_runtime

    rt = get_runtime()
    rt._max_cameras = 1
    cam1 = _add_camera(db, store, _base_cfg(tmp_path))
    cam2 = _add_camera(db, store, _base_cfg(tmp_path))

    assert client.post(f"/api/edge/cameras/{cam1.id}/start").status_code == 200
    try:
        r = client.post(f"/api/edge/cameras/{cam2.id}/start")
        assert r.status_code == 409
        assert "capacity" in r.json()["detail"].lower()
    finally:
        client.post(f"/api/edge/cameras/{cam1.id}/stop")


def test_edge_supervisor_removes_deactivated_camera(client, db, store, tmp_path):
    from app.edge import get_runtime

    cam = _add_camera(db, store, _base_cfg(tmp_path))
    assert client.post(f"/api/edge/cameras/{cam.id}/start").status_code == 200
    assert get_runtime().has_camera(str(cam.id))

    cam.is_active = False
    db.commit()

    r = client.get("/api/edge/cameras")
    assert r.status_code == 200
    row = {c["camera_id"]: c for c in r.json()}[str(cam.id)]
    assert row["health"] == "DISABLED"
    assert not get_runtime().has_camera(str(cam.id))


def test_edge_demo_video_upload(client, db, store, tmp_path):
    # Synthetic video
    path = os.path.join(str(tmp_path), "sample_demo.mp4")
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 8, (64, 48))
    for i in range(16):
        img = np.zeros((48, 64, 3), dtype=np.uint8)
        img[:] = (i * 10, 50, 80)
        vw.write(img)
    vw.release()

    with open(path, "rb") as f:
        r = client.post(
            "/api/edge/demo-video",
            files={"file": ("sample_demo.mp4", f, "video/mp4")},
            data={"name": "My CCTV Test", "store_id": str(store.id)},
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["name"] == "My CCTV Test"
    assert data["running"] is True
    assert data["camera_id"]
    client.post(f"/api/edge/cameras/{data['camera_id']}/stop")


def test_edge_demo_sample_people(client, db, store):
    r = client.post(
        "/api/edge/demo-sample",
        data={"sample_key": "people", "store_id": str(store.id)},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "Customer Flow" in data["name"]
    assert data["running"] is True
    client.post(f"/api/edge/cameras/{data['camera_id']}/stop")
