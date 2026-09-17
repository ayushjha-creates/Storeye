"""M22 — data integrity check service tests (PostgreSQL).

Verifies the read-only IntegrityCheckService detects injected inconsistencies
and reports a clean database as OK. The service must never mutate data, so each
test asserts on the report only.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import (
    Alert,
    Batch,
    Camera,
    DemoScenarioState,
    Inventory,
    Product,
    Store,
)
from app.services.integrity_check_service import IntegrityCheckService

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
def session(engine):
    with engine.begin() as conn:
        Base.metadata.drop_all(conn)
        Base.metadata.create_all(conn)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = factory()
    try:
        yield s
    finally:
        s.close()


def make_store(session, name="Test Store", is_demo=False) -> Store:
    store = Store(name=name, is_demo=is_demo)
    session.add(store)
    session.commit()
    return store


def make_product(session, store) -> Product:
    p = Product(store_id=store.id, sku="SKU-1", name="Widget")
    session.add(p)
    session.commit()
    return p


def test_clean_database_is_ok(session):
    store = make_store(session)
    product = make_product(session, store)
    session.add(Inventory(store_id=store.id, product_id=product.id, quantity=5))
    session.commit()

    report = IntegrityCheckService(session).run()
    assert report.ok is True
    assert report.errors == []
    assert report.stats["stores"] == 1
    assert report.stats["inventory"] == 1


def test_negative_inventory_is_flagged(session):
    store = make_store(session)
    product = make_product(session, store)
    session.add(Inventory(store_id=store.id, product_id=product.id, quantity=-3))
    session.commit()

    report = IntegrityCheckService(session).run()
    assert report.ok is False
    assert any(f.check == "inventory_negative" for f in report.errors)


def test_duplicate_inventory_is_flagged(session):
    store = make_store(session)
    product = make_product(session, store)
    # Legitimately impossible via the ORM (unique constraint), so simulate the
    # corruption this check exists to catch.
    session.execute(text("ALTER TABLE inventory DROP CONSTRAINT uq_inventory_store_product"))
    session.execute(
        Inventory.__table__.insert(),
        [
            {"id": uuid4(), "store_id": store.id, "product_id": product.id, "quantity": 1},
            {"id": uuid4(), "store_id": store.id, "product_id": product.id, "quantity": 2},
        ],
    )
    session.commit()

    report = IntegrityCheckService(session).run()
    assert any(f.check == "inventory_duplicate" for f in report.errors)


def test_batch_expiry_before_manufacturing_is_flagged(session):
    store = make_store(session)
    product = make_product(session, store)
    session.add(
        Batch(
            store_id=store.id,
            product_id=product.id,
            batch_number="B1",
            manufacturing_date=date(2026, 6, 1),
            expiry_date=date(2026, 5, 1),
            quantity=10,
        )
    )
    session.commit()

    report = IntegrityCheckService(session).run()
    assert any(f.check == "batch_expiry_before_manufacturing" for f in report.errors)


def test_invalid_camera_type_is_flagged(session):
    store = make_store(session)
    session.add(Camera(store_id=store.id, name="Cam", camera_type="hologram"))
    session.commit()

    report = IntegrityCheckService(session).run()
    assert any(f.check == "camera_invalid_type" for f in report.errors)


def test_invalid_alert_values_are_flagged(session):
    store = make_store(session)
    now = datetime.now(timezone.utc)
    session.add(
        Alert(
            store_id=store.id,
            alert_type="NOT_A_TYPE",
            severity="BANANA",
            status="OPEN",
            title="bad",
            first_detected_at=now,
            last_detected_at=now,
        )
    )
    session.commit()

    report = IntegrityCheckService(session).run()
    assert any(f.check == "alert_invalid_values" for f in report.errors)


def test_demo_state_on_non_demo_store_is_flagged(session):
    store = make_store(session, is_demo=False)
    session.add(DemoScenarioState(store_id=store.id, active_key="NORMAL_STORE"))
    session.commit()

    report = IntegrityCheckService(session).run()
    assert any(f.check == "demo_isolation" for f in report.errors)


def test_privacy_check_passes_on_real_schema(session):
    report = IntegrityCheckService(session).run()
    assert not any(f.check == "privacy_media_columns" for f in report.findings)
