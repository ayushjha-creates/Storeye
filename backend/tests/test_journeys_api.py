"""M19 — Anonymous Customer Journeys API route tests.

Exercises the real HTTP surface:
    GET /api/journeys
    GET /api/journeys/summary
    GET /api/journeys/{global_person_id}
    GET /api/zones/{zone_id}/analytics
plus camera config validation for the new M19 keys (zone_id, zones,
next_cameras, reid).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.db.base import Base
from app.main import app
from app.models import CONF_HIGH, Camera, Store, Zone
from app.services.journeys import JourneyService

pytestmark = pytest.mark.pg

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://storeye@localhost:5433/storeye_test",
)


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

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _seed_journey(session_factory, store_id, zone_id):
    """Create one deterministic multi-camera journey via the real service."""
    session = session_factory()
    try:
        cam_a = Camera(
            store_id=store_id, name="Cam A", location="a",
            camera_type="usb", is_active=True,
        )
        cam_b = Camera(
            store_id=store_id, name="Cam B", location="b",
            camera_type="usb", is_active=True,
        )
        session.add_all([cam_a, cam_b])
        session.commit()
        session.refresh(cam_a)
        session.refresh(cam_b)

        svc = JourneyService(session)
        pid = "demo-global-alice"
        t = datetime.now(timezone.utc)
        svc.upsert_track_association(
            store_id=store_id, global_person_id=pid, camera_id=cam_a.id,
            track_id=1, confidence=CONF_HIGH, timestamp=t,
        )
        svc.upsert_track_association(
            store_id=store_id, global_person_id=pid, camera_id=cam_b.id,
            track_id=2, confidence=CONF_HIGH,
            timestamp=t + timedelta(minutes=3),
        )
        svc.record_transition(
            store_id=store_id, global_person_id=pid,
            from_camera_id=cam_a.id, to_camera_id=cam_b.id,
            timestamp=t + timedelta(minutes=3), confidence=CONF_HIGH,
        )
        svc.open_zone_visit(
            store_id=store_id, global_person_id=pid, zone_id=zone_id,
            camera_id=cam_b.id, timestamp=t + timedelta(minutes=3),
            confidence=CONF_HIGH,
        )
        return pid, str(cam_a.id), str(cam_b.id)
    finally:
        session.close()


def test_journeys_list_summary_detail_and_404(client, session_factory):
    # Create store
    r = client.post("/api/stores", json={"name": "Journey Mart"})
    store_id = r.json()["id"]

    # Create zone
    zr = client.post(
        "/api/zones",
        json={"store_id": store_id, "name": "Billing"},
    )
    assert zr.status_code == 201
    zone_id = zr.json()["id"]

    pid, cam_a, cam_b = _seed_journey(session_factory, store_id, zone_id)

    # List journeys
    lst = client.get(f"/api/journeys?store_id={store_id}")
    assert lst.status_code == 200
    body = lst.json()
    assert body["total"] == 1
    assert body["items"][0]["global_person_id"] == pid
    assert body["items"][0]["camera_count"] == 2

    # Summary KPIs
    summary = client.get(f"/api/journeys/summary?store_id={store_id}")
    assert summary.status_code == 200
    s = summary.json()
    assert s["total_visitors"] == 1
    assert s["active_visitors"] == 1

    # Detail
    detail = client.get(f"/api/journeys/{pid}?store_id={store_id}")
    assert detail.status_code == 200
    d = detail.json()
    assert len(d["track_associations"]) == 2
    assert len(d["transitions"]) == 1
    types = {e["type"] for e in d["timeline"]}
    assert {"track", "transition", "zone_enter"}.issubset(types)

    # 404 for unknown journey
    missing = client.get(
        f"/api/journeys/does-not-exist?store_id={store_id}"
    )
    assert missing.status_code == 404

    # Summary route is stable even with /summary path
    assert client.get(f"/api/journeys/summary?store_id={store_id}").status_code == 200

    # Wrong store => nothing (store-scoped)
    r2 = client.post("/api/stores", json={"name": "Other Store"})
    other = r2.json()["id"]
    empty = client.get(f"/api/journeys?store_id={other}")
    assert empty.json()["total"] == 0


def test_zone_analytics_endpoint(client, session_factory):
    # Create store
    r = client.post("/api/stores", json={"name": "Zone Mart"})
    store_id = r.json()["id"]

    # Create zone
    zr = client.post(
        "/api/zones",
        json={"store_id": store_id, "name": "Grocery"},
    )
    assert zr.status_code == 201
    zone_id = zr.json()["id"]

    _seed_journey(session_factory, store_id, zone_id)

    # Get analytics
    resp = client.get(f"/api/zones/{zone_id}/analytics")
    assert resp.status_code == 200
    a = resp.json()
    assert a["zone_id"] == zone_id
    assert a["visits_total"] == 1
    assert a["visitors_unique"] == 1
    assert a["currently_inside"] == 1  # zone visit left open


def test_camera_config_validates_m19_keys(client):
    # Create store
    r = client.post("/api/stores", json={"name": "Config Mart"})
    store_id = r.json()["id"]

    # Valid camera with M19 config
    cam = {
        "name": "Entrance",
        "store_id": store_id,
        "camera_type": "usb",
        "config": {
            "kind": "usb",
            "person_detection": True,
            "zone_id": "zone-entrance-1",
            "next_cameras": ["cam-aisle-1"],
            "zones": [
                {"zone_id": "zone-entrance-1", "bbox": [0.0, 0.0, 1.0, 1.0]}
            ],
            "reid": {"embedding_refresh_interval_seconds": 10},
        },
    }
    resp = client.post("/api/cameras", json=cam)
    assert resp.status_code == 201
    assert resp.json()["config"]["next_cameras"] == ["cam-aisle-1"]
    assert resp.json()["config"]["zone_id"] == "zone-entrance-1"

    # Invalid bbox (3 elements instead of 4)
    bad = client.post(
        "/api/cameras",
        json={
            "name": "Bad",
            "store_id": store_id,
            "camera_type": "usb",
            "config": {
                "zones": [
                    {"zone_id": "z", "bbox": [0, 1, 2]}
                ],
            },
        },
    )
    assert bad.status_code == 422