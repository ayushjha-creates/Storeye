"""Milestone 11 — API tests for the Storeye FastAPI layer.

Tests run against the isolated PostgreSQL test database (storeye_test).
They exercise real HTTP endpoints (via TestClient) with the session
dependency overridden to the test engine, plus direct service calls where
appropriate to assert persistence invariants (e.g. inventory atomicity,
observation non-mutation, reconciliation information-only).

Coverage:
    - CRUD for every entity group
    - request validation (422), not-found (404), duplicate constraints (409)
    - inventory transaction behavior (movement created, atomic)
    - batch behavior (create, duplicate conflict, metadata update)
    - observation persistence (never mutates inventory)
    - reconciliation persistence (never mutates inventory)
    - bill creation, sale creation
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.main import app
from app.api.deps import get_db
from app.models import (
    Bill,
    Inventory,
    InventoryMovement,
    Notification,
    Observation,
    Product,
    ReconciliationResult,
    Sale,
    Store,
)

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
    from sqlalchemy.orm import sessionmaker

    with engine.begin() as conn:
        Base.metadata.drop_all(conn)
        Base.metadata.create_all(conn)
    factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )
    yield factory


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


@pytest.fixture()
def db(session_factory):
    session = session_factory()
    yield session
    session.close()


def _make_store(db, name="Test Store") -> Store:
    s = Store(name=name, timezone="Asia/Kolkata")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _make_product(db, store_id, sku="SKU-1", name="Product 1", price=10) -> Product:
    p = Product(
        store_id=store_id,
        sku=sku,
        name=name,
        selling_price=price,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


# ===========================================================================
# Health (legacy SQLite diagnostics — must still respond)
# ===========================================================================
def test_health_readiness_and_metrics(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "healthy"
    assert "app" in body and "version" in body


# ===========================================================================
# Store CRUD + validation + not-found
# ===========================================================================
def test_store_crud(client, db):
    # create
    r = client.post("/api/stores", json={"name": "Corner Shop"})
    assert r.status_code == 201
    store = r.json()
    store_id = store["id"]
    assert store["timezone"] == "Asia/Kolkata"
    assert UUID(store_id)

    # list
    r = client.get("/api/stores")
    assert r.status_code == 200
    assert r.json()["total"] == 1

    # get
    r = client.get(f"/api/stores/{store_id}")
    assert r.status_code == 200
    assert r.json()["name"] == "Corner Shop"

    # update
    r = client.patch(f"/api/stores/{store_id}", json={"name": "Renamed"})
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed"

    # delete
    r = client.delete(f"/api/stores/{store_id}")
    assert r.status_code == 204
    r = client.get(f"/api/stores/{store_id}")
    assert r.status_code == 404


def test_store_validation_and_not_found(client):
    # empty name -> 422
    r = client.post("/api/stores", json={"name": ""})
    assert r.status_code == 422
    # missing name -> 422
    r = client.post("/api/stores", json={})
    assert r.status_code == 422
    # not found
    r = client.get("/api/stores/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


# ===========================================================================
# User CRUD
# ===========================================================================
def test_user_crud(client, db):
    store = _make_store(db)
    r = client.post(
        "/api/users",
        json={"store_id": str(store.id), "name": "Owner", "role": "OWNER"},
    )
    assert r.status_code == 201
    user_id = r.json()["id"]
    assert r.json()["store_id"] == str(store.id)

    r = client.get(f"/api/users/{user_id}")
    assert r.status_code == 200
    r = client.patch(f"/api/users/{user_id}", json={"role": "ASSOCIATE"})
    assert r.status_code == 200
    assert r.json()["role"] == "ASSOCIATE"
    r = client.delete(f"/api/users/{user_id}")
    assert r.status_code == 204


def test_user_store_not_found(client):
    r = client.post(
        "/api/users",
        json={
            "store_id": "00000000-0000-0000-0000-000000000000",
            "name": "Ghost",
        },
    )
    assert r.status_code == 404


# ===========================================================================
# Camera / Zone / Shelf / Product CRUD
# ===========================================================================
def test_camera_crud(client, db):
    store = _make_store(db)
    sid = str(store.id)
    r = client.post(
        "/api/cameras",
        json={"store_id": sid, "name": "Front", "camera_type": "usb"},
    )
    assert r.status_code == 201
    cam_id = r.json()["id"]
    assert r.json()["is_active"] is True
    r = client.get("/api/cameras")
    assert r.json()["total"] == 1
    r = client.patch(f"/api/cameras/{cam_id}", json={"is_active": False})
    assert r.json()["is_active"] is False
    r = client.delete(f"/api/cameras/{cam_id}")
    assert r.status_code == 204


def test_zone_shelf_product_flow(client, db):
    store = _make_store(db)
    sid = str(store.id)
    r = client.post("/api/zones", json={"store_id": sid, "name": "Snacks"})
    assert r.status_code == 201
    zone_id = r.json()["id"]

    r = client.post(
        "/api/shelves",
        json={"store_id": sid, "zone_id": zone_id, "code": "A1"},
    )
    assert r.status_code == 201
    shelf_id = r.json()["id"]

    r = client.post(
        "/api/products",
        json={
            "store_id": sid,
            "sku": "MAGGI",
            "name": "Maggi Noodles",
            "selling_price": 14.0,
        },
    )
    assert r.status_code == 201
    product_id = r.json()["id"]

    # product duplicate SKU per store -> 409
    r = client.post(
        "/api/products",
        json={"store_id": sid, "sku": "MAGGI", "name": "Duplicate"},
    )
    assert r.status_code == 409

    # shelf duplicate code per store -> 409
    r = client.post(
        "/api/shelves",
        json={"store_id": sid, "zone_id": zone_id, "code": "A1"},
    )
    assert r.status_code == 409

    # shelf with unknown zone -> 404
    r = client.post(
        "/api/shelves",
        json={
            "store_id": sid,
            "zone_id": "00000000-0000-0000-0000-000000000000",
            "code": "B2",
        },
    )
    assert r.status_code == 404

    # checkout reads
    r = client.get(f"/api/zones/{zone_id}")
    assert r.status_code == 200
    r = client.get(f"/api/shelves/{shelf_id}")
    assert r.status_code == 200
    r = client.get(f"/api/products/{product_id}")
    assert r.status_code == 200
    r = client.get("/api/products", params={"category": "x"})
    assert r.status_code == 200


# ===========================================================================
# Inventory: atomic mutation via domain service
# ===========================================================================
def test_receive_stock_creates_movement_and_updates_inventory(client, db):
    store = _make_store(db)
    product = _make_product(db, store.id, sku="RICE", name="Rice")
    sid, pid = str(store.id), str(product.id)

    # initial inventory (zero aggregate)
    r = client.get(f"/api/inventory/stores/{sid}/products/{pid}")
    assert r.status_code == 200
    assert r.json()["quantity"] == 0

    # receive stock -> movement + inventory update
    r = client.post(
        "/api/inventory/receive",
        json={"store_id": sid, "product_id": pid, "quantity_change": 50},
    )
    assert r.status_code == 201
    mv = r.json()
    assert mv["quantity_change"] == 50
    assert mv["movement_type"] == "PURCHASE"

    # aggregate updated
    r = client.get(f"/api/inventory/stores/{sid}/products/{pid}")
    assert r.json()["quantity"] == 50

    # movement persisted
    r = client.get(f"/api/inventory/stores/{sid}/products/{pid}/movements")
    assert r.json()["total"] == 1

    # summary reflects it
    r = client.get(f"/api/inventory/stores/{sid}/products/{pid}/summary")
    assert r.json()["aggregate_quantity"] == 50


def test_inventory_requires_real_product(client, db):
    store = _make_store(db)
    r = client.post(
        "/api/inventory/receive",
        json={
            "store_id": str(store.id),
            "product_id": "00000000-0000-0000-0000-000000000000",
            "quantity_change": 10,
        },
    )
    assert r.status_code == 404


# ===========================================================================
# Batch behavior
# ===========================================================================
def test_batch_create_duplicate_conflict(client, db):
    store = _make_store(db)
    product = _make_product(db, store.id, sku="BATCH-SKU", name="Batch Prod")
    sid, pid = str(store.id), str(product.id)

    r = client.post(
        "/api/inventory/batches",
        json={
            "store_id": sid,
            "product_id": pid,
            "batch_number": "B1",
            "manufacturing_date": "2026-01-10",
            "expiry_date": "2026-12-31",
            "mrp": 150.0,
            "quantity": 0,
        },
    )
    assert r.status_code == 201
    batch_id = r.json()["id"]
    assert r.json()["expiry_date_precision"] == "day"

    # duplicate batch number for same product/store -> 409
    r = client.post(
        "/api/inventory/batches",
        json={"store_id": sid, "product_id": pid, "batch_number": "B1"},
    )
    assert r.status_code == 409

    # metadata update via PATCH
    r = client.patch(
        f"/api/inventory/batches/{batch_id}", json={"mrp": 160.0}
    )
    assert r.status_code == 200
    assert r.json()["mrp"] == "160.00"

    # not found
    r = client.get("/api/inventory/batches/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


def test_receive_stock_scoped_to_batch_updates_batch_and_inventory(client, db):
    store = _make_store(db)
    product = _make_product(db, store.id, sku="RICE-B", name="Rice B")
    sid, pid = str(store.id), str(product.id)

    r = client.post(
        "/api/inventory/batches",
        json={"store_id": sid, "product_id": pid, "batch_number": "BR1", "quantity": 0},
    )
    batch_id = r.json()["id"]

    r = client.post(
        "/api/inventory/receive",
        json={
            "store_id": sid,
            "product_id": pid,
            "quantity_change": 20,
            "batch_id": batch_id,
        },
    )
    assert r.status_code == 201

    # aggregate and batch both update atomically
    agg = client.get(f"/api/inventory/stores/{sid}/products/{pid}").json()
    assert agg["quantity"] == 20
    batch = client.get(f"/api/inventory/batches/{batch_id}").json()
    assert batch["quantity"] == 20


def test_batch_invalid_expiry_precision_returns_422(client, db):
    store = _make_store(db)
    product = _make_product(db, store.id, sku="PREC", name="Prec")
    r = client.post(
        "/api/inventory/batches",
        json={
            "store_id": str(store.id),
            "product_id": str(product.id),
            "batch_number": "P1",
            "expiry_date_precision": "decade",
        },
    )
    assert r.status_code == 422


# ===========================================================================
# Customer / Sale / Bill
# ===========================================================================
def test_customer_sale_bill_flow(client, db):
    store = _make_store(db)
    product = _make_product(db, store.id, sku="B1-T", name="B1")
    sid, pid = str(store.id), str(product.id)

    # customer
    r = client.post(
        "/api/customers",
        json={"store_id": sid, "mobile": "9123456789", "name": "Rahul"},
    )
    assert r.status_code == 201
    cust_id = r.json()["id"]

    # sale with items
    r = client.post(
        "/api/sales",
        json={
            "store_id": sid,
            "subtotal": 42.0,
            "tax_total": 0.0,
            "total": 42.0,
            "payment_method": "cash",
            "customer_id": cust_id,
            "items": [
                {
                    "product_id": pid,
                    "quantity": 3,
                    "unit_price": 14.0,
                    "line_total": 42.0,
                }
            ],
        },
    )
    assert r.status_code == 201
    sale_id = r.json()["id"]
    assert len(r.json()["items"]) == 1

    # bill linked to sale + customer
    r = client.post(
        "/api/bills",
        json={
            "store_id": sid,
            "bill_number": "BILL-100",
            "sale_id": sale_id,
            "customer_id": cust_id,
            "subtotal": 42.0,
            "total": 42.0,
            "items": [
                {
                    "product_id": pid,
                    "quantity": 3,
                    "unit_price": 14.0,
                    "line_total": 42.0,
                }
            ],
        },
    )
    assert r.status_code == 201
    bill_id = r.json()["id"]
    assert r.json()["delivery_status"] == "DRAFT"

    # bill update delivery status
    r = client.patch(f"/api/bills/{bill_id}", json={"delivery_status": "SENT"})
    assert r.status_code == 200
    assert r.json()["delivery_status"] == "SENT"

    # bill with missing sale -> 404
    r = client.post(
        "/api/bills",
        json={
            "store_id": sid,
            "bill_number": "BILL-X",
            "sale_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert r.status_code == 404


def test_sale_with_unknown_product_returns_404(client, db):
    store = _make_store(db)
    r = client.post(
        "/api/sales",
        json={
            "store_id": str(store.id),
            "subtotal": 10.0,
            "total": 10.0,
            "items": [
                {
                    "product_id": "00000000-0000-0000-0000-000000000000",
                    "quantity": 1,
                    "unit_price": 10.0,
                    "line_total": 10.0,
                }
            ],
        },
    )
    assert r.status_code == 404


def test_sale_with_unknown_store_returns_404(client, db):
    r = client.post(
        "/api/sales",
        json={
            "store_id": "00000000-0000-0000-0000-000000000000",
            "subtotal": 1.0,
            "total": 1.0,
            "items": [],
        },
    )
    assert r.status_code == 404


def test_inventory_adjust_reduces_quantity(client, db):
    store = _make_store(db)
    product = _make_product(db, store.id, sku="ADJ-1", name="Adj")
    sid, pid = str(store.id), str(product.id)

    client.post(
        "/api/inventory/receive",
        json={"store_id": sid, "product_id": pid, "quantity_change": 30},
    )
    r = client.post(
        "/api/inventory/adjust",
        json={"store_id": sid, "product_id": pid, "quantity_change": -5},
    )
    assert r.status_code == 200
    assert r.json()["quantity_change"] == -5

    inv = client.get(f"/api/inventory/stores/{sid}/products/{pid}").json()
    assert inv["quantity"] == 25

    # movement ledger got an ADJUSTMENT entry
    mv = client.get(
        f"/api/inventory/stores/{sid}/products/{pid}/movements"
    ).json()
    kinds = [m["movement_type"] for m in mv["items"]]
    assert "ADJUSTMENT" in kinds


def test_inventory_adjust_insufficient_stock_returns_422(client, db):
    store = _make_store(db)
    product = _make_product(db, store.id, sku="ADJ-2", name="Adj2")
    sid, pid = str(store.id), str(product.id)

    client.post(
        "/api/inventory/receive",
        json={"store_id": sid, "product_id": pid, "quantity_change": 3},
    )
    # trying to remove more than available -> 422 (with strict-mode flag)
    r = client.post(
        "/api/inventory/adjust",
        json={
            "store_id": sid,
            "product_id": pid,
            "quantity_change": -50,
            "require_sufficient_stock": True,
        },
    )
    assert r.status_code == 422

    # inventory unchanged after rejected start-level mutation
    inv = client.get(f"/api/inventory/stores/{sid}/products/{pid}").json()
    assert inv["quantity"] == 3


# ===========================================================================
# Notifications
# ===========================================================================def test_notification_crud(client, db):
    store = _make_store(db)
    sid = str(store.id)
    r = client.post(
        "/api/notifications",
        json={
            "store_id": sid,
            "notif_type": "LOW_STOCK",
            "title": "Low stock alert",
            "severity": "WARNING",
        },
    )
    assert r.status_code == 201
    nid = r.json()["id"]
    assert r.json()["is_read"] is False
    r = client.patch(f"/api/notifications/{nid}", json={"is_read": True})
    assert r.json()["is_read"] is True
    r = client.get("/api/notifications", params={"is_read": True})
    assert r.json()["total"] == 1
    r = client.delete(f"/api/notifications/{nid}")
    assert r.status_code == 204


# ===========================================================================
# AI Observations: persistence, no inventory mutation
# ===========================================================================
def test_observation_persistence_does_not_mutate_inventory(client, db):
    store = _make_store(db)
    product = _make_product(db, store.id, sku="OBS-1", name="Obs")
    sid, pid = str(store.id), str(product.id)

    # establish inventory quantity = 100
    client.post(
        "/api/inventory/receive",
        json={"store_id": sid, "product_id": pid, "quantity_change": 100},
    )

    # record an AI observation saying we "saw" this product
    r = client.post(
        "/api/observations",
        json={
            "observation_type": "PRODUCT",
            "store_id": sid,
            "product_id": pid,
            "confidence": 0.9,
            "bbox": [1, 2, 3, 4],
        },
    )
    assert r.status_code == 201
    obs_id = r.json()["id"]
    assert r.json()["observation_type"] == "PRODUCT"

    # observation must NOT have changed inventory
    inv = client.get(f"/api/inventory/stores/{sid}/products/{pid}").json()
    assert inv["quantity"] == 100

    # list + get observation
    r = client.get("/api/observations", params={"store_id": sid})
    assert r.json()["total"] == 1
    r = client.get(f"/api/observations/{obs_id}")
    assert r.status_code == 200


def test_invalid_observation_type_returns_422(client, db):
    store = _make_store(db)
    r = client.post(
        "/api/observations",
        json={"observation_type": "NOT_A_TYPE", "store_id": str(store.id)},
    )
    assert r.status_code == 422


def test_observation_list_pagination_and_filters(client, db):
    """List uses server-side pagination; total is the full match count."""
    store = _make_store(db)
    sid = str(store.id)
    base = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
    for i, (typ, conf) in enumerate(
        [
            ("PERSON", 0.9),
            ("PERSON", 0.8),
            ("PRODUCT", 0.7),
            ("PERSON", 0.6),
            ("PRODUCT", 0.5),
        ]
    ):
        client.post(
            "/api/observations",
            json={
                "observation_type": typ,
                "store_id": sid,
                "track_id": i if typ == "PERSON" else None,
                "confidence": conf,
                "bbox": [1, 1, 10, 10],
                "observed_at": (base + timedelta(minutes=i)).isoformat(),
            },
        )

    r = client.get("/api/observations", params={"store_id": sid})
    assert r.status_code == 200
    assert r.json()["total"] == 5
    assert len(r.json()["items"]) == 5

    # offset + limit pagination keeps the true total
    r = client.get("/api/observations", params={"store_id": sid, "limit": 2, "offset": 2})
    assert r.json()["total"] == 5
    assert len(r.json()["items"]) == 2

    # type + confidence + time-range filters
    r = client.get("/api/observations", params={"store_id": sid, "observation_type": "PERSON"})
    assert r.json()["total"] == 3
    r = client.get("/api/observations", params={"store_id": sid, "confidence_min": 0.8})
    assert r.json()["total"] == 2
    r = client.get(
        "/api/observations",
        params={
            "store_id": sid,
            "from": (base + timedelta(minutes=2)).isoformat(),
            "to": (base + timedelta(minutes=4)).isoformat(),
        },
    )
    assert r.json()["total"] == 3

    # invalid observation type filter -> 422
    r = client.get("/api/observations", params={"store_id": sid, "observation_type": "NOPE"})
    assert r.status_code == 422


def test_observation_summary_aggregates_read_only(client, db):
    """Summary aggregates a bounded window without mutating anything."""
    store = _make_store(db)
    sid = str(store.id)
    now = datetime.now(timezone.utc)
    for i in range(3):
        client.post(
            "/api/observations",
            json={
                "observation_type": "PERSON",
                "store_id": sid,
                "track_id": 1 if i < 2 else 2,
                "confidence": 0.9,
                "bbox": [1, 1, 5, 5],
                "observed_at": now.isoformat(),
            },
        )
    for _ in range(2):
        client.post(
            "/api/observations",
            json={
                "observation_type": "PRODUCT",
                "store_id": sid,
                "confidence": 0.8,
                "bbox": [1, 1, 5, 5],
                "observed_at": now.isoformat(),
            },
        )

    r = client.get("/api/observations/summary", params={"store_id": sid, "hours": 24})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5
    assert body["by_type"] == {"PERSON": 3, "PRODUCT": 2}
    assert body["distinct_tracks"] == 2
    assert body["avg_confidence"] is not None
    assert body["last_observed_at"] is not None
    assert isinstance(body["activity"], list)
    # hourly buckets must exactly cover the recorded observations (no double count)
    assert sum(b["count"] for b in body["activity"]) == 5
    assert max(b["count"] for b in body["activity"]) == 5

    # restrict aggregation to one type
    r = client.get(
        "/api/observations/summary",
        params={"store_id": sid, "observation_type": "PERSON"},
    )
    assert r.json()["total"] == 3

    # summary by camera id works and returns zero when nothing matches
    r = client.get(
        "/api/observations/summary",
        params={"store_id": sid, "camera_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_camera_config_and_type_validation(client, db):
    """Camera config is validated so the Edge runtime cannot be fed junk."""
    store = _make_store(db)
    sid = str(store.id)

    ok = client.post(
        "/api/cameras",
        json={
            "store_id": sid,
            "name": "File Cam",
            "camera_type": "file",
            "config": {"kind": "file", "source": "/tmp/video.mp4"},
        },
    )
    assert ok.status_code == 201

    # invalid config.kind -> 422
    r = client.post(
        "/api/cameras",
        json={"store_id": sid, "name": "Bad", "camera_type": "usb", "config": {"kind": "webcam"}},
    )
    assert r.status_code == 422
    # invalid camera_type -> 422
    r = client.post(
        "/api/cameras", json={"store_id": sid, "name": "Bad", "camera_type": "webcam"}
    )
    assert r.status_code == 422
    # non-string source -> 422
    r = client.post(
        "/api/cameras",
        json={"store_id": sid, "name": "Bad", "camera_type": "usb", "config": {"source": 123}},
    )
    assert r.status_code == 422
    # non-boolean pipeline flag -> 422
    r = client.post(
        "/api/cameras",
        json={
            "store_id": sid,
            "name": "Bad",
            "camera_type": "usb",
            "config": {"person_detection": "yes"},
        },
    )
    assert r.status_code == 422

    # update path is validated too
    cam_id = ok.json()["id"]
    r = client.patch(f"/api/cameras/{cam_id}", json={"config": {"kind": "rtsp"}})
    assert r.status_code == 200
    r = client.patch(f"/api/cameras/{cam_id}", json={"config": {"kind": "garbage"}})
    assert r.status_code == 422


# ===========================================================================
# Reconciliation: information only, never mutates inventory
# ===========================================================================
def test_reconciliation_persists_result_without_mutating_inventory(client, db):
    store = _make_store(db)
    product = _make_product(db, store.id, sku="REC-1", name="Rec")
    sid, pid = str(store.id), str(product.id)

    # inventory = 10
    client.post(
        "/api/inventory/receive",
        json={"store_id": sid, "product_id": pid, "quantity_change": 10},
    )
    before = client.get(f"/api/inventory/stores/{sid}/products/{pid}").json()[
        "quantity"
    ]
    assert before == 10

    # record AI observations showing a different count
    now = datetime.now(timezone.utc)
    for _ in range(3):
        client.post(
            "/api/observations",
            json={
                "observation_type": "PRODUCT",
                "store_id": sid,
                "product_id": pid,
                "confidence": 0.9,
                "bbox": [10, 10, 60, 60],
                "observed_at": now.isoformat(),
            },
        )

    # run reconciliation
    r = client.post(
        "/api/reconciliation/run",
        json={
            "store_id": sid,
            "product_ids": [pid],
            "start": (now - timedelta(hours=1)).isoformat(),
            "end": (now + timedelta(hours=1)).isoformat(),
        },
    )
    assert r.status_code == 201
    results = r.json()
    assert results["total"] >= 1
    first = results["items"][0]
    assert first["product_id"] == pid
    assert first["status"] in {
        "MATCH",
        "POSSIBLE_SURPLUS",
        "POSSIBLE_SHORTAGE",
        "REVIEW_REQUIRED",
    }

    # inventory MUST remain unchanged after reconciliation
    after = client.get(f"/api/inventory/stores/{sid}/products/{pid}").json()[
        "quantity"
    ]
    assert after == before

    # persisted result listable by store
    r = client.get("/api/reconciliation", params={"store_id": sid})
    assert r.status_code == 200
    assert r.json()["total"] >= 1

    # fetch single result
    result_id = r.json()["items"][0]["id"]
    r = client.get(f"/api/reconciliation/{result_id}")
    assert r.status_code == 200


def test_reconciliation_store_not_found(client):
    r = client.post(
        "/api/reconciliation/run",
        json={
            "store_id": "00000000-0000-0000-0000-000000000000",
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-01-02T00:00:00Z",
        },
    )
    assert r.status_code == 404
