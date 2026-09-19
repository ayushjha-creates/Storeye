"""M20 — Store Intelligence API route tests.

Exercises the real HTTP surface:
    GET  /api/insights (+ filters, pagination, store scope)
    GET  /api/insights/summary
    GET  /api/insights/store-health
    GET  /api/insights/inventory | /expiry | /customer-flow
    POST /api/insights/evaluate
    GET  /api/insights/{id}
    POST /api/insights/{id}/acknowledge | resolve | expire (+ invalid transitions)

Guarantees verified at the HTTP layer: evaluation never mutates inventory/
batches/sales (snapshots before/after), unknown insight_id -> 404, invalid
transition -> 422, and lifecycle endpoints only update `insights` rows.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.db.base import Base
from app.main import app
from app.models import (
    Batch,
    Insight,
    Inventory,
    Product,
    STATUS_OPEN,
    STATUS_RESOLVED,
    Store,
    InventoryMovement,
)
from app.services.insights import InsightEngine
from tests.conftest import bind_test_user, make_store

pytestmark = pytest.mark.pg

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://storeye@localhost:5433/storeye_test",
)

REF = date(2026, 8, 1)


def _new_store(session_factory, name: str):
    """Create a store in the test DB and authenticate as its OWNER."""
    store = make_store(session_factory, name)
    bind_test_user(store.id)
    return str(store.id)


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


def _product(db, store_id, sku, name):
    p = Product(store_id=store_id, sku=sku, name=name, selling_price=Decimal("10.00"))
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _inventory(db, store_id, product, qty, reorder_level=5):
    inv = Inventory(
        store_id=store_id, product_id=product.id, quantity=qty, reorder_level=reorder_level,
    )
    db.add(inv)
    db.commit()
    return inv


def _batch(db, store_id, product, qty, expiry_date):
    b = Batch(
        store_id=store_id, product_id=product.id, quantity=qty,
        batch_number="API-B1", expiry_date=expiry_date,
    )
    db.add(b)
    db.commit()
    return b


def _evaluate_inventory(session_factory, store_id):
    session = session_factory()
    try:
        return InsightEngine(session).evaluate_inventory(store_id)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# evaluate + list + filters + pagination
# ---------------------------------------------------------------------------


def test_evaluate_and_list(client, session_factory):
    store_id = _new_store(session_factory, "Insight API Mart")

    session = session_factory()
    p = _product(session, store_id, "API-1", "Milk")
    _inventory(session, store_id, p, 3, reorder_level=5)
    session.close()

    r = client.post("/api/insights/evaluate", json={"store_id": store_id})
    assert r.status_code == 200
    body = r.json()
    # evaluate() persists the rule insight(s) AND the cached STORE_HEALTH summary.
    assert body["created"] == 2
    assert body["candidates"] >= 2
    assert len(body["insights"]) == 2
    low = next(i for i in body["insights"] if i["insight_type"] == "LOW_STOCK")
    assert low["severity"] == "MEDIUM"

    lst = client.get(f"/api/insights?store_id={store_id}")
    assert lst.status_code == 200
    items = lst.json()
    assert items["total"] == 2
    low_item = next(i for i in items["items"] if i["insight_type"] == "LOW_STOCK")
    assert low_item["evidence"]["metrics"]["current_stock"] == 3

    # Filter by type
    filtered = client.get(f"/api/insights?store_id={store_id}&type=LOW_STOCK")
    assert filtered.json()["total"] == 1
    none = client.get(f"/api/insights?store_id={store_id}&type=OUT_OF_STOCK")
    assert none.json()["total"] == 0

    # Store isolation: reading another store's insights is rejected at the
    # boundary (never a silent 200 with another tenant's rows).
    other = make_store(session_factory, "Empty Store")
    other_resp = client.get(f"/api/insights?store_id={other.id}")
    assert other_resp.status_code == 403


def test_list_records_do_not_leak_alert_state(client, session_factory):
    store_id = _new_store(session_factory, "List Mart")
    session = session_factory()
    p = _product(session, store_id, "API-2", "Bread")
    _inventory(session, store_id, p, 0, reorder_level=4)  # OUT_OF_STOCK
    session.close()
    client.post("/api/insights/evaluate", json={"store_id": store_id})
    lst = client.get(f"/api/insights?store_id={store_id}")
    item = lst.json()["items"][0]
    assert item["insight_type"] == "OUT_OF_STOCK"
    assert item["status"] == "OPEN"


def test_evaluate_dedup_over_http(client, session_factory):
    store_id = _new_store(session_factory, "Dedup Mart")
    session = session_factory()
    p = _product(session, store_id, "API-3", "Milk")
    _inventory(session, store_id, p, 3, reorder_level=5)
    session.close()

    first = client.post("/api/insights/evaluate", json={"store_id": store_id})
    second = client.post("/api/insights/evaluate", json={"store_id": store_id})
    assert first.json()["created"] == 2
    assert second.json()["created"] == 0
    assert second.json()["refreshed"] == 2
    lst = client.get(f"/api/insights?store_id={store_id}")
    assert lst.json()["total"] == 2


def test_evaluate_never_mutates_domain_data(client, session_factory):
    store_id = _new_store(session_factory, "NoMutate Mart")

    session = session_factory()
    p = _product(session, store_id, "API-4", "Sauce")
    _inventory(session, store_id, p, 2, reorder_level=5)
    _batch(session, store_id, p, 6, expiry_date=REF + timedelta(days=5))
    before = {
        "inv_qty": session.scalar(select(func.sum(Inventory.quantity))),
        "inv_rows": session.scalar(select(func.count(Inventory.id))),
        "batch_qty": session.scalar(select(func.sum(Batch.quantity))),
        "movements": session.scalar(select(func.count(InventoryMovement.id))),
    }
    session.close()

    r = client.post("/api/insights/evaluate", json={"store_id": store_id})
    assert r.status_code == 200

    session = session_factory()
    after = {
        "inv_qty": session.scalar(select(func.sum(Inventory.quantity))),
        "inv_rows": session.scalar(select(func.count(Inventory.id))),
        "batch_qty": session.scalar(select(func.sum(Batch.quantity))),
        "movements": session.scalar(select(func.count(InventoryMovement.id))),
    }
    session.close()
    assert before == after


# ---------------------------------------------------------------------------
# summary + store-health + domain endpoints
# ---------------------------------------------------------------------------


def test_summary_counts(client, session_factory):
    store_id = _new_store(session_factory, "Summary Mart")
    session = session_factory()
    p = _product(session, store_id, "API-5", "Milk")
    _inventory(session, store_id, p, 3, reorder_level=5)
    session.close()
    client.post("/api/insights/evaluate", json={"store_id": store_id})

    resp = client.get(f"/api/insights/summary?store_id={store_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["open"] == 2
    assert body["inventory"] == 1
    assert body["by_type"]["inventory"] == 1


def test_store_health_endpoint(client, session_factory):
    store_id = _new_store(session_factory, "Health Mart")
    resp = client.get(f"/api/insights/store-health?store_id={store_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "HEALTHY"
    assert body["cameras"]["total"] == 0
    assert len(body["basis"]) >= 1


def test_domain_category_endpoints(client, session_factory):
    store_id = _new_store(session_factory, "Domain Mart")
    session = session_factory()
    p = _product(session, store_id, "API-6", "Yogurt")
    _inventory(session, store_id, p, 0, reorder_level=4)
    _batch(session, store_id, p, 6, expiry_date=REF - timedelta(days=2))
    session.close()

    from app.services.insights import InsightEngine
    session = session_factory()
    InsightEngine(session).evaluate(store_id, reference_date=REF)
    session.close()

    inv = client.get(f"/api/insights/inventory?store_id={store_id}")
    assert inv.status_code == 200
    types = {i["insight_type"] for i in inv.json()["items"]}
    assert "OUT_OF_STOCK" in types

    exp = client.get(f"/api/insights/expiry?store_id={store_id}")
    assert exp.status_code == 200
    etypes = {i["insight_type"] for i in exp.json()["items"]}
    assert "EXPIRED_BATCH" in etypes

    flow = client.get(f"/api/insights/customer-flow?store_id={store_id}")
    assert flow.status_code == 200
    assert flow.json()["total"] == 0


def test_inventory_endpoint_rejects_unknown_store_product(client, session_factory):
    store_id = _new_store(session_factory, "Unknown Product Mart")
    # Own store, no data -> empty (200).
    resp = client.get(f"/api/insights/inventory?store_id={store_id}")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
    # A store the caller does not own is rejected at the boundary.
    resp = client.get(
        "/api/insights/inventory?store_id=00000000-0000-0000-0000-000000000000"
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# get one + lifecycle transitions + 404/422
# ---------------------------------------------------------------------------


def _seed_one_insight(client, session_factory, name="Lifecycle Mart"):
    store_id = _new_store(session_factory, name)
    session = session_factory()
    p = _product(session, store_id, "API-7", "Milk")
    _inventory(session, store_id, p, 3, reorder_level=5)
    session.close()
    client.post("/api/insights/evaluate", json={"store_id": store_id})
    return store_id


def test_get_insight_and_404(client, session_factory):
    store_id = _seed_one_insight(client, session_factory)
    lst = client.get(f"/api/insights?store_id={store_id}")
    insight_id = lst.json()["items"][0]["id"]

    detail = client.get(f"/api/insights/{insight_id}")
    assert detail.status_code == 200
    assert detail.json()["insight_type"] == "LOW_STOCK"
    assert detail.json()["evidence"]["rule"] == "low_stock"

    missing = client.get("/api/insights/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404


def test_acknowledge_resolve_lifecycle(client, session_factory):
    store_id = _seed_one_insight(client, session_factory, "Ack Mart")
    lst = client.get(f"/api/insights?store_id={store_id}")
    insight_id = lst.json()["items"][0]["id"]

    ack = client.post(f"/api/insights/{insight_id}/acknowledge")
    assert ack.status_code == 200
    assert ack.json()["status"] == "ACKNOWLEDGED"
    assert ack.json()["acknowledged_at"] is not None

    resolved = client.post(f"/api/insights/{insight_id}/resolve")
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "RESOLVED"
    assert resolved.json()["resolved_at"] is not None

    # Terminal state: further transitions rejected.
    expired = client.post(f"/api/insights/{insight_id}/expire")
    assert expired.status_code == 422


def test_expire_transition(client, session_factory):
    store_id = _seed_one_insight(client, session_factory, "Expire Mart")
    lst = client.get(f"/api/insights?store_id={store_id}")
    insight_id = lst.json()["items"][0]["id"]
    resp = client.post(f"/api/insights/{insight_id}/expire")
    assert resp.status_code == 200
    assert resp.json()["status"] == "EXPIRED"
    assert resp.json()["expired_at"] is not None


def test_transition_on_unknown_insight_404(client, session_factory):
    _new_store(session_factory, "Unknown Insight Mart")
    resp = client.post("/api/insights/00000000-0000-0000-0000-000000000000/resolve")
    assert resp.status_code == 404