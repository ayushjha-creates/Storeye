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

pytestmark = [
    pytest.mark.pg,
]

TEST_DB_URL = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg2://storeye@localhost:5433/storeye_test")


class _FakeRegistry:
    def new_person_tracker(self):
        return FakePersonTracker()

    def get_product_detector(self):
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
    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
    from app.db.session import init_engine
    init_engine(TEST_DB_URL)

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    # Inject a fake-model runtime for deterministic edge runs.
    fake_rt = EdgeRuntime(registry=_FakeRegistry())
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
    return s


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
    time.sleep(1.2)
    client.post(f"/api/edge/cameras/{str(cam.id)}/stop")

    obs_count = db.query(Observation).count()
    inv_count = db.query(Inventory).count()
    assert obs_count > 0  # AI observations were persisted
    assert inv_count == 0  # and NOTHING touched inventory
