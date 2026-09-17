"""M21 — Demo scenario HTTP API tests."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timezone

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.api.routers.demo import DEFAULT_RESET_KEY
from app.core.config import get_settings
from app.db.base import Base
from app.main import app
from app.models import (
    Alert,
    Batch,
    Camera,
    GlobalPersonSession,
    Insight,
    Inventory,
    Observation,
    PersonCameraTransition,
    PersonTrackAssociation,
    Product,
    Shelf,
    Store,
    Zone,
    ZoneVisit,
)
from app.services.demo import demo_data
from scripts.seed_demo import DEMO_STORE_ID, reset_demo_store, seed_with_session

pytestmark = pytest.mark.pg

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://storeye@localhost:5433/storeye_test",
)

AUTH = {"X-Demo-Reset-Key": DEFAULT_RESET_KEY}


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


def test_list_scenarios_endpoint(client):
    r = client.get("/api/demo/scenarios")
    assert r.status_code == 200
    body = r.json()
    assert body["demo_mode"] is True
    assert len(body["scenarios"]) == 12
    keys = {s["key"] for s in body["scenarios"]}
    assert demo_data.SCENARIO_NORMAL in keys
    assert demo_data.SCENARIO_COMBINED_CRISIS in keys


def test_get_scenario_endpoint_and_404(client):
    r = client.get(f"/api/demo/scenarios/{demo_data.SCENARIO_LOW_STOCK}")
    assert r.status_code == 200
    assert r.json()["key"] == demo_data.SCENARIO_LOW_STOCK

    r404 = client.get("/api/demo/scenarios/NOPE")
    assert r404.status_code == 404


def test_status_endpoint(client):
    r = client.get("/api/demo/status")
    assert r.status_code == 200
    assert r.json()["demo_store"] == "Storeye Demo Mart"


def test_activate_requires_key(client):
    r = client.post(f"/api/demo/scenarios/{demo_data.SCENARIO_LOW_STOCK}/activate")
    assert r.status_code == 403


def test_activate_with_key_persists_state(client, session_factory):
    r = client.post(
        f"/api/demo/scenarios/{demo_data.SCENARIO_LOW_STOCK}/activate", headers=AUTH
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["active_key"] == demo_data.SCENARIO_LOW_STOCK
    assert body["scenario"]["key"] == demo_data.SCENARIO_LOW_STOCK
    assert body["metrics"]

    # Browser refresh must still show the scenario: read from a fresh session.
    with session_factory() as s:
        insights = list(
            s.scalars(select(Insight).where(Insight.store_id == DEMO_STORE_ID))
        )
    assert any(i.insight_type == "LOW_STOCK" for i in insights)

    status = client.get("/api/demo/status").json()
    assert status["active_key"] == demo_data.SCENARIO_LOW_STOCK


def test_invalid_activate_404(client):
    r = client.post("/api/demo/scenarios/BOGUS/activate", headers=AUTH)
    assert r.status_code == 404


def test_reset_endpoint(client):
    client.post(
        f"/api/demo/scenarios/{demo_data.SCENARIO_OUT_OF_STOCK}/activate", headers=AUTH
    )
    r = client.post("/api/demo/reset", headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["active_key"] == demo_data.SCENARIO_NORMAL


def test_reset_requires_key(client):
    r = client.post("/api/demo/reset")
    assert r.status_code == 403


def test_demo_mode_disabled_hides_endpoints(client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    get_settings.cache_clear()
    try:
        assert client.get("/api/demo/scenarios").status_code == 404
        assert client.get("/api/demo/status").status_code == 404
        assert client.post("/api/demo/reset", headers=AUTH).status_code == 404
    finally:
        monkeypatch.delenv("DEMO_MODE", raising=False)
        get_settings.cache_clear()


def test_scenarios_never_touch_non_demo_store(client, session_factory):
    with session_factory() as s:
        s.add(Store(name="Another Real Store", is_demo=False))
        s.commit()
        real_id = s.scalars(
            select(Store.id).where(Store.name == "Another Real Store")
        ).one()

    client.post(
        f"/api/demo/scenarios/{demo_data.SCENARIO_COMBINED_CRISIS}/activate",
        headers=AUTH,
    )

    with session_factory() as s:
        assert list(s.scalars(select(Insight).where(Insight.store_id == real_id))) == []
        other = s.get(Store, real_id)
        assert other.is_demo is False


# ---------------------------------------------------------------------------
# M23 — demo reset must restore an identical baseline (deterministic reset)
# ---------------------------------------------------------------------------

FIXED_NOW = datetime(2025, 1, 15, 12, 0, tzinfo=timezone.utc)

_BASELINE_MODELS = [
    Insight,
    Alert,
    Observation,
    Inventory,
    Batch,
    Shelf,
    Camera,
    Product,
    Zone,
    GlobalPersonSession,
    PersonCameraTransition,
    PersonTrackAssociation,
    ZoneVisit,
]


def _demo_counts(session) -> dict:
    return {
        model.__tablename__: int(
            session.execute(select(func.count()).select_from(model)).scalar_one()
        )
        for model in _BASELINE_MODELS
    }


def test_demo_reset_is_deterministic_and_isolated(session_factory):
    with session_factory() as s:
        s.add(Store(name="Untouched Real Store", is_demo=False))
        s.commit()

    with session_factory() as s:
        seed_with_session(s, now=FIXED_NOW)
        first = _demo_counts(s)
        assert sum(first.values()) > 0

        reset_demo_store(s)
        seed_with_session(s, now=FIXED_NOW)
        second = _demo_counts(s)

    assert first == second

    with session_factory() as s:
        real = s.scalars(
            select(Store).where(Store.name == "Untouched Real Store")
        ).one()
        assert real.is_demo is False
        demo = s.get(Store, DEMO_STORE_ID)
        assert demo is not None and demo.is_demo is True
