"""Milestone 9 tests: AI <-> Inventory reconciliation.

Integration tests against the isolated storeye_test database. They verify the
ReconciliationService accurately compares persisted PRODUCT observations with
recorded inventory, uses a conservative counting strategy, honours the time
window and camera scope, and CRITICALLY never modifies inventory / never creates
movements or batches.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import (
    Batch,
    Camera,
    Inventory,
    InventoryMovement,
    Observation,
    Product,
    Store,
    ReconciliationResult,
    REC_MATCH,
    REC_SURPLUS,
    REC_SHORTAGE,
    REC_REVIEW,
)
from app.services.observations import ObservationService
from app.services.reconciliation import ReconciliationService

pytestmark = pytest.mark.pg

TEST_DB_URL = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg2://storeye@localhost:5433/storeye_test")


@pytest.fixture(scope="session")
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
    session = Session(engine)
    yield session
    session.close()


@pytest.fixture()
def store(db) -> Store:
    s = Store(name="Recon Store", timezone="Asia/Kolkata")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@pytest.fixture()
def product(db, store) -> Product:
    p = Product(store_id=store.id, sku="REC-LAYS", name="Lays", selling_price=10)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture()
def other_product(db, store) -> Product:
    p = Product(store_id=store.id, sku="REC-MAGGI", name="Maggi", selling_price=14)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture()
def camera(db, store) -> Camera:
    c = Camera(name="recon-cam-1", store_id=store.id)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


BASE = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
WIN = (BASE, BASE + timedelta(hours=1))


def _set_inventory(db, store, product, qty):
    inv = db.scalar(select(Inventory).where(Inventory.store_id == store.id, Inventory.product_id == product.id))
    if inv is None:
        inv = Inventory(store_id=store.id, product_id=product.id, quantity=qty)
    else:
        inv.quantity = qty
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv


def _record(db, store, product, camera, *, conf=0.9, bbox=None, frame=0, track=None,
            observed_at=None):
    svc = ObservationService(db)
    kw = dict(store_id=store.id, camera_id=camera.id,
              product_id=product.id, confidence=conf, bbox=bbox,
              frame_number=frame, observed_at=observed_at or BASE)
    if track is not None:
        kw["track_id"] = track
    return svc.record_observation(observation_type="PRODUCT", **kw)


def _recon(db):
    return ReconciliationService(db)


def _count(db, model):
    return db.query(model).count()


# ---------------------------------------------------------------------------
# 1. Matching inventory
# ---------------------------------------------------------------------------
def test_matching_inventory(db, store, product, camera):
    _set_inventory(db, store, product, 2)
    # Two distinct instances observed in one frame (non-overlapping bboxes).
    _record(db, store, product, camera, bbox=[0, 0, 10, 10])
    _record(db, store, product, camera, bbox=[100, 0, 110, 10])
    r = _recon(db).reconcile_product(store_id=store.id, product_id=product.id, camera_id=camera.id, start=WIN[0], end=WIN[1])
    assert r.status == REC_MATCH
    assert r.database_quantity == 2
    assert r.ai_observed_quantity == 2
    assert r.difference == 0


# ---------------------------------------------------------------------------
# 2. Possible shortage
# ---------------------------------------------------------------------------
def test_possible_shortage(db, store, product, camera):
    _set_inventory(db, store, product, 5)
    # AI saw only 3 distinct instances.
    _record(db, store, product, camera, bbox=[0, 0, 10, 10])
    _record(db, store, product, camera, bbox=[100, 0, 110, 10])
    _record(db, store, product, camera, bbox=[200, 0, 210, 10])
    r = _recon(db).reconcile_product(store_id=store.id, product_id=product.id, camera_id=camera.id, start=WIN[0], end=WIN[1])
    assert r.status == REC_SHORTAGE
    assert r.database_quantity == 5
    assert r.ai_observed_quantity == 3
    assert r.difference == -2


# ---------------------------------------------------------------------------
# 3. Possible surplus
# ---------------------------------------------------------------------------
def test_possible_surplus(db, store, product, camera):
    _set_inventory(db, store, product, 5)
    # AI saw 8 distinct instances simultaneously (all in a single frame).
    for k in range(8):
        _record(db, store, product, camera, bbox=[k * 30, 0, k * 30 + 10, 10], frame=0)
    r = _recon(db).reconcile_product(store_id=store.id, product_id=product.id, camera_id=camera.id, start=WIN[0], end=WIN[1])
    assert r.status == REC_SURPLUS
    assert r.ai_observed_quantity == 8
    assert r.difference == 3


# ---------------------------------------------------------------------------
# 4. Multiple observations of same tracked instance counted once
# ---------------------------------------------------------------------------
def test_tracked_instance_dedup(db, store, product, camera):
    # One tracked instance across 3 frames -> observed = 1, not 3.
    for frame in (100, 101, 102):
        _record(db, store, product, camera, track=42, bbox=[0, 0, 10, 10], frame=frame)
    r = _recon(db).reconcile_product(store_id=store.id, product_id=product.id, camera_id=camera.id, start=WIN[0], end=WIN[1])
    assert r.ai_observed_quantity == 1
    assert r.details["counting_rule"] == "distinct_track_ids"


def test_three_distinct_tracked_instances(db, store, product, camera):
    _set_inventory(db, store, product, 3)
    for track in (101, 102, 103):
        _record(db, store, product, camera, track=track, bbox=[0, 0, 10, 10])
    r = _recon(db).reconcile_product(store_id=store.id, product_id=product.id, camera_id=camera.id, start=WIN[0], end=WIN[1])
    assert r.ai_observed_quantity == 3
    assert r.status == REC_MATCH


# ---------------------------------------------------------------------------
# 5. Time-window filtering
# ---------------------------------------------------------------------------
def test_time_window_filtering(db, store, product, camera):
    _set_inventory(db, store, product, 1)
    _record(db, store, product, camera, bbox=[0, 0, 10, 10], observed_at=BASE)             # in window
    _record(db, store, product, camera, bbox=[0, 0, 10, 10], observed_at=BASE + timedelta(hours=5))  # out of window
    r = _recon(db).reconcile_product(store_id=store.id, product_id=product.id, camera_id=camera.id, start=WIN[0], end=WIN[1])
    assert r.ai_observed_quantity == 1  # only the in-window observation counted


# ---------------------------------------------------------------------------
# 6. Different products
# ---------------------------------------------------------------------------
def test_different_products_isolated(db, store, product, other_product, camera):
    _set_inventory(db, store, product, 1)
    _set_inventory(db, store, other_product, 1)
    _record(db, store, product, camera, bbox=[0, 0, 10, 10])
    _record(db, store, other_product, camera, bbox=[0, 0, 10, 10])
    rp = _recon(db).reconcile_store(store_id=store.id, start=WIN[0], end=WIN[1], camera_id=camera.id)
    findings = {r.product_id: r for r in rp}
    assert findings[product.id].ai_observed_quantity == 1
    assert findings[other_product.id].ai_observed_quantity == 1


# ---------------------------------------------------------------------------
# 7. Camera-scoped reconciliation (no cross-camera double count)
# ---------------------------------------------------------------------------
def test_camera_scope_no_fusion(db, store, product):
    _set_inventory(db, store, product, 1)
    cam1 = Camera(name="c1", store_id=store.id); db.add(cam1)
    cam2 = Camera(name="c2", store_id=store.id); db.add(cam2); db.commit(); db.refresh(cam1); db.refresh(cam2)
    # Same physical shelf seen by both cameras -> same bbox.
    _record(db, store, product, cam1, bbox=[0, 0, 10, 10])
    _record(db, store, product, cam2, bbox=[0, 0, 10, 10])
    results = _recon(db).reconcile_store(store_id=store.id, start=WIN[0], end=WIN[1])
    # One result per camera, each saw 1 -> never summed to 2.
    assert len(results) == 2
    assert {r.camera_id for r in results} == {cam1.id, cam2.id}
    assert all(r.ai_observed_quantity == 1 for r in results)


# ---------------------------------------------------------------------------
# 8. Missing product_id observations ignored
# ---------------------------------------------------------------------------
def test_missing_product_id_ignored(db, store, product, camera):
    _set_inventory(db, store, product, 3)
    # Observed product instances...
    _record(db, store, product, camera, bbox=[0, 0, 10, 10])
    _record(db, store, product, camera, bbox=[100, 0, 110, 10])
    # ...plus an uncertain detection with no product_id -> must be ignored.
    ObservationService(db).record_product_observation(
        store_id=store.id, camera_id=camera.id, product_id=None, confidence=0.9, bbox=[200, 0, 210, 10])
    r = _recon(db).reconcile_product(store_id=store.id, product_id=product.id, camera_id=camera.id, start=WIN[0], end=WIN[1])
    assert r.ai_observed_quantity == 2


# ---------------------------------------------------------------------------
# 9. Low-confidence observations ignored per documented rule
# ---------------------------------------------------------------------------
def test_low_confidence_ignored(db, store, product, camera):
    _set_inventory(db, store, product, 1)
    _record(db, store, product, camera, conf=0.95, bbox=[0, 0, 10, 10])  # counts
    _record(db, store, product, camera, conf=0.1, bbox=[100, 0, 110, 10])  # below 0.5 -> ignored
    r = _recon(db).reconcile_product(store_id=store.id, product_id=product.id, camera_id=camera.id, start=WIN[0], end=WIN[1])
    assert r.ai_observed_quantity == 1


# ---------------------------------------------------------------------------
# 14. Empty observation window -> REVIEW_REQUIRED
# ---------------------------------------------------------------------------
def test_empty_window_review_required(db, store, product, camera):
    _set_inventory(db, store, product, 5)
    r = _recon(db).reconcile_product(store_id=store.id, product_id=product.id, camera_id=camera.id, start=WIN[0], end=WIN[1])
    assert r.status == REC_REVIEW
    assert r.ai_observed_quantity == 0
    assert r.confidence is None


# ---------------------------------------------------------------------------
# 15-4. No tracking: one instance across frames counts once (max per frame)
# ---------------------------------------------------------------------------
def test_one_instance_across_frames_without_track(db, store, product, camera):
    _set_inventory(db, store, product, 1)
    # Same bbox in 3 frames, no track_id -> max simultaneous per frame = 1.
    for frame in (100, 101, 102):
        _record(db, store, product, camera, bbox=[0, 0, 10, 10], frame=frame)
    r = _recon(db).reconcile_product(store_id=store.id, product_id=product.id, camera_id=camera.id, start=WIN[0], end=WIN[1])
    assert r.ai_observed_quantity == 1
    assert r.details["counting_rule"] == "max_simultaneous_per_frame"


def test_three_distinct_instances_without_track(db, store, product, camera):
    _set_inventory(db, store, product, 3)
    _record(db, store, product, camera, bbox=[0, 0, 10, 10])
    _record(db, store, product, camera, bbox=[100, 0, 110, 10])
    _record(db, store, product, camera, bbox=[200, 0, 210, 10])
    r = _recon(db).reconcile_product(store_id=store.id, product_id=product.id, camera_id=camera.id, start=WIN[0], end=WIN[1])
    assert r.ai_observed_quantity == 3


# ---------------------------------------------------------------------------
# 10-13. No inventory/movement/batch mutation; existing data intact (MANDATORY)
# ---------------------------------------------------------------------------
def test_no_inventory_modification_or_movement_creation(db, store, product, camera):
    _set_inventory(db, store, product, 5)
    before_inv = db.query(Inventory).filter_by(store_id=store.id, product_id=product.id).one().quantity
    before_movements = _count(db, InventoryMovement)
    before_batches = _count(db, Batch)

    # AI observed 15 instances (recorded before reconciliation runs).
    for k in range(15):
        _record(db, store, product, camera, bbox=[k * 10, 0, k * 10 + 5, 10])

    # Snapshot observation count AFTER recording, BEFORE reconciliation.
    before_recon_observations = _count(db, Observation)
    r = _recon(db).reconcile_product(store_id=store.id, product_id=product.id, camera_id=camera.id, start=WIN[0], end=WIN[1])
    assert r.ai_observed_quantity == 15

    after_inv = db.query(Inventory).filter_by(store_id=store.id, product_id=product.id).one().quantity
    after_movements = _count(db, InventoryMovement)
    after_batches = _count(db, Batch)
    after_recon_observations = _count(db, Observation)

    assert after_inv == before_inv == 5            # inventory unchanged
    assert after_movements == before_movements     # no new movements
    assert after_batches == before_batches         # no new batches
    assert after_recon_observations == before_recon_observations  # reconciliation added NO observations


def test_no_batch_creation(db, store, product, camera):
    before_batches = _count(db, Batch)
    _set_inventory(db, store, product, 1)
    # Record observations that LOOK like expiry-ish product data, then reconcile.
    _record(db, store, product, camera, bbox=[0, 0, 10, 10])
    r = _recon(db).reconcile_product(store_id=store.id, product_id=product.id, camera_id=camera.id, start=WIN[0], end=WIN[1])
    assert _count(db, Batch) == before_batches
    assert r.store_id == store.id


# Test helper for "existing data intact" style assertions across a set of tables.
def test_existing_data_counts_all_intact(db, store, product, other_product, camera):
    _set_inventory(db, store, product, 2)
    _set_inventory(db, store, other_product, 4)
    _record(db, store, product, camera, bbox=[0, 0, 10, 10])
    _record(db, store, product, camera, bbox=[100, 0, 110, 10])
    snapshot = {t: _count(db, m) for t, m in [
        ("Inventory", Inventory), ("Movement", InventoryMovement), ("Batch", Batch), ("Observation", Observation)]}
    _recon(db).reconcile_store(store_id=store.id, start=WIN[0], end=WIN[1], camera_id=camera.id)
    after = {t: _count(db, m) for t, m in [
        ("Inventory", Inventory), ("Movement", InventoryMovement), ("Batch", Batch), ("Observation", Observation)]}
    assert snapshot == after  # only ReconciliationResult rows were added