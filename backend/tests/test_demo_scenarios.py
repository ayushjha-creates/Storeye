"""M21 — Demo & Scenario Engine tests (engine layer).

Verifies the deterministic scenario catalog against a real PostgreSQL test DB:
    * every scenario activates and produces its expected M20 signal,
    * activation is idempotent/deterministic,
    * reset restores the healthy NORMAL_STORE baseline,
    * the demo-store guard refuses non-demo stores,
    * scenario operations never touch a non-demo store's data.

These tests exercise the SERVICE layer (DemoScenarioEngine), not just HTTP.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models import (
    Alert,
    Camera,
    Insight,
    Inventory,
    Observation,
    OBS_PERSON,
    PersonTrackAssociation,
    Product,
    STATUS_OPEN,
    Store,
)
from app.services.demo import (
    DemoScenarioEngine,
    NotADemoStore,
    UnknownScenario,
    demo_data,
)
from scripts.seed_demo import DEMO_STORE_ID, DEMO_STORE_NAME, fixed

pytestmark = pytest.mark.pg

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://storeye@localhost:5433/storeye_test",
)

# M15 shelf intelligence bounds its observation window with the wall clock, so
# the scenario clock must sit just inside that window (mirrors the M20 tests).
NOW = datetime.now(timezone.utc) - timedelta(minutes=1)


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
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _active_insights(db: Session, store_id=DEMO_STORE_ID):
    return list(
        db.scalars(
            select(Insight).where(
                Insight.store_id == store_id,
                Insight.status.in_(["OPEN", "ACKNOWLEDGED"]),
            )
        )
    )


def _types(db: Session, store_id=DEMO_STORE_ID) -> dict:
    out: dict = {}
    for i in _active_insights(db, store_id):
        out.setdefault(i.insight_type, []).append(i.severity)
    return out


def _activate(db: Session, key: str) -> dict:
    return DemoScenarioEngine(db).activate(key, now=NOW)


# ---------------------------------------------------------------------------
# catalog + status
# ---------------------------------------------------------------------------


def test_list_scenarios_catalog(db):
    infos = DemoScenarioEngine(db).list_scenarios()
    keys = {i.key for i in infos}
    assert keys == set(demo_data.VALID_SCENARIO_KEYS)
    assert len(infos) == 13
    assert all(i.name and i.description and i.expected for i in infos)


def test_status_reports_demo_store(db):
    DemoScenarioEngine(db).reset(now=NOW)
    status = DemoScenarioEngine(db).status()
    assert status["store_exists"] is True
    assert status["store_is_demo"] is True
    assert status["active_key"] == demo_data.SCENARIO_NORMAL
    assert status["scenario"]["key"] == demo_data.SCENARIO_NORMAL


def test_unknown_scenario_rejected(db):
    with pytest.raises(UnknownScenario):
        _activate(db, "DOES_NOT_EXIST")


def test_non_demo_store_guard(db):
    other = Store(name="Real Store", is_demo=False)
    db.add(other)
    db.commit()
    eng = DemoScenarioEngine(db, demo_store_id=other.id)
    with pytest.raises(NotADemoStore):
        eng.activate(demo_data.SCENARIO_LOW_STOCK, now=NOW)


# ---------------------------------------------------------------------------
# per-scenario behaviour (A–T)
# ---------------------------------------------------------------------------


def test_normal_store_is_healthy(db):
    _activate(db, demo_data.SCENARIO_NORMAL)
    types = _types(db)
    assert "STORE_HEALTH" in types
    health = [i for i in _active_insights(db) if i.insight_type == "STORE_HEALTH"][0]
    assert health.title == "Store health: HEALTHY"
    assert not any(sev in ("MEDIUM", "HIGH", "CRITICAL") for sevs in types.values() for sev in sevs)


def test_low_stock_scenario(db):
    _activate(db, demo_data.SCENARIO_LOW_STOCK)
    types = _types(db)
    assert "LOW_STOCK" in types
    maggi = db.scalars(
        select(Product).where(Product.store_id == DEMO_STORE_ID, Product.sku == "MAGGI-2MIN")
    ).one()
    inv = db.scalars(
        select(Inventory).where(
            Inventory.store_id == DEMO_STORE_ID, Inventory.product_id == maggi.id
        )
    ).one()
    assert 0 < inv.quantity < inv.reorder_level


def test_out_of_stock_scenario(db):
    _activate(db, demo_data.SCENARIO_OUT_OF_STOCK)
    types = _types(db)
    assert "HIGH" in types["OUT_OF_STOCK"]
    alerts = db.scalars(
        select(Alert).where(Alert.store_id == DEMO_STORE_ID, Alert.status == STATUS_OPEN)
    ).all()
    assert any(a.alert_type == "SHORTAGE" for a in alerts)


def test_expiry_risk_scenario(db):
    _activate(db, demo_data.SCENARIO_EXPIRY_RISK)
    types = _types(db)
    assert "EXPIRY_RISK" in types
    assert "EXPIRED_BATCH" in types
    assert "HIGH" in types["EXPIRED_BATCH"]


def test_low_shelf_backstock_scenario(db):
    _activate(db, demo_data.SCENARIO_LOW_SHELF_BACKSTOCK)
    types = _types(db)
    assert "LOW_SHELF_AVAILABILITY" in types
    # Inventory is available -> no low/out-of-stock insight.
    assert "LOW_STOCK" not in types
    assert "OUT_OF_STOCK" not in types
    maggi = db.scalars(
        select(Product).where(Product.store_id == DEMO_STORE_ID, Product.sku == "MAGGI-2MIN")
    ).one()
    inv = db.scalars(
        select(Inventory).where(
            Inventory.store_id == DEMO_STORE_ID, Inventory.product_id == maggi.id
        )
    ).one()
    assert inv.quantity > inv.reorder_level


def test_misplacement_scenario(db):
    _activate(db, demo_data.SCENARIO_MISPLACEMENT)
    types = _types(db)
    assert "MISPLACEMENT" in types
    # Never escalated to certainty: M15/M20 wording stays "possible".
    mis = [i for i in _active_insights(db) if i.insight_type == "MISPLACEMENT"][0]
    assert "possible" in mis.title.lower()
    assert "intentional" not in mis.title.lower()


def test_high_traffic_scenario(db):
    _activate(db, demo_data.SCENARIO_HIGH_TRAFFIC)
    types = _types(db)
    assert "HIGH_TRAFFIC_ZONE" in types
    assert "INFO" in types["HIGH_TRAFFIC_ZONE"]


def test_high_dwell_scenario(db):
    _activate(db, demo_data.SCENARIO_HIGH_DWELL)
    types = _types(db)
    assert "HIGH_DWELL_ZONE" in types
    assert "INFO" in types["HIGH_DWELL_ZONE"]


def test_multi_camera_journey_scenario(db):
    _activate(db, demo_data.SCENARIO_MULTI_CAMERA_JOURNEY)
    alice = str(fixed("person:alice"))
    cams = db.scalars(
        select(PersonTrackAssociation.camera_id).where(
            PersonTrackAssociation.store_id == DEMO_STORE_ID,
            PersonTrackAssociation.global_person_id == alice,
        )
    ).all()
    assert len(set(cams)) >= 3


def test_camera_offline_scenario(db):
    _activate(db, demo_data.SCENARIO_CAMERA_OFFLINE)
    types = _types(db)
    assert "CAMERA_HEALTH" in types
    assert "HIGH" in types["CAMERA_HEALTH"]
    offline = [i for i in _active_insights(db) if i.insight_type == "CAMERA_HEALTH"]
    assert len(offline) == 1
    assert "Roof" in offline[0].title or "Roof" in (offline[0].description or "")
    alerts = db.scalars(
        select(Alert).where(Alert.store_id == DEMO_STORE_ID, Alert.status == STATUS_OPEN)
    ).all()
    assert any(a.alert_type == "CAMERA_OFFLINE" for a in alerts)


def test_combined_crisis_scenario(db):
    _activate(db, demo_data.SCENARIO_COMBINED_CRISIS)
    types = _types(db)
    assert "OUT_OF_STOCK" in types
    assert "EXPIRED_BATCH" in types
    assert "LOW_SHELF_AVAILABILITY" in types
    assert "MISPLACEMENT" in types
    assert "CAMERA_HEALTH" in types
    alerts = db.scalars(
        select(Alert).where(Alert.store_id == DEMO_STORE_ID)
    ).all()
    assert len(alerts) >= 3


def test_smart_receiving_scenario_is_healthy(db):
    _activate(db, demo_data.SCENARIO_SMART_RECEIVING)
    health = [i for i in _active_insights(db) if i.insight_type == "STORE_HEALTH"][0]
    assert health.title == "Store health: HEALTHY"


# ---------------------------------------------------------------------------
# determinism / reset / isolation
# ---------------------------------------------------------------------------


def test_activation_is_deterministic(db):
    _activate(db, demo_data.SCENARIO_LOW_STOCK)
    first_types = sorted((i.insight_type, i.severity, i.entity_id) for i in _active_insights(db))
    first_qty = db.scalar(
        select(Inventory.quantity)
        .join(Product, Product.id == Inventory.product_id)
        .where(Product.sku == "MAGGI-2MIN", Inventory.store_id == DEMO_STORE_ID)
    )
    _activate(db, demo_data.SCENARIO_LOW_STOCK)
    second_types = sorted((i.insight_type, i.severity, i.entity_id) for i in _active_insights(db))
    second_qty = db.scalar(
        select(Inventory.quantity)
        .join(Product, Product.id == Inventory.product_id)
        .where(Product.sku == "MAGGI-2MIN", Inventory.store_id == DEMO_STORE_ID)
    )
    assert first_types == second_types
    assert first_qty == second_qty == 8


def test_scenario_does_not_inherit_previous_scenario(db):
    _activate(db, demo_data.SCENARIO_OUT_OF_STOCK)
    assert "OUT_OF_STOCK" in _types(db)
    _activate(db, demo_data.SCENARIO_LOW_SHELF_BACKSTOCK)
    types = _types(db)
    assert "OUT_OF_STOCK" not in types
    assert "LOW_SHELF_AVAILABILITY" in types


def test_reset_restores_healthy_baseline(db):
    _activate(db, demo_data.SCENARIO_OUT_OF_STOCK)
    assert "OUT_OF_STOCK" in _types(db)
    DemoScenarioEngine(db).reset(now=NOW)
    assert DemoScenarioEngine(db).status()["active_key"] == demo_data.SCENARIO_NORMAL
    health = [i for i in _active_insights(db) if i.insight_type == "STORE_HEALTH"][0]
    assert health.title == "Store health: HEALTHY"


def test_production_store_untouched_by_scenarios(db):
    other = Store(name="Production Store", is_demo=False)
    db.add(other)
    db.flush()
    prod = Product(
        store_id=other.id, sku="PROD-1", name="Prod Item", selling_price=10
    )
    db.add(prod)
    db.flush()
    db.add(
        Inventory(
            store_id=other.id, product_id=prod.id, quantity=7, reorder_level=5
        )
    )
    db.commit()

    _activate(db, demo_data.SCENARIO_COMBINED_CRISIS)

    inv = db.scalars(
        select(Inventory).where(Inventory.store_id == other.id)
    ).one()
    assert inv.quantity == 7
    assert db.scalars(
        select(Insight).where(Insight.store_id == other.id)
    ).all() == []
    assert db.scalars(
        select(Alert).where(Alert.store_id == other.id)
    ).all() == []


def test_camera_freshness_after_normal(db):
    _activate(db, demo_data.SCENARIO_NORMAL)
    total_active = db.scalar(
        select(func.count(Camera.id)).where(
            Camera.store_id == DEMO_STORE_ID, Camera.is_active.is_(True)
        )
    )
    assert total_active == 5
    assert "CAMERA_HEALTH" not in _types(db)
