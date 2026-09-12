"""Milestone 7 tests: Inventory + Batch domain.

Integration tests run against an isolated PostgreSQL database
(storeye_test) using the explicit BatchService / InventoryService domain
operations. They verify batch creation, expiry/metadata persistence,
uniqueness, transactional inventory updates and rollback safety.
"""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import Batch, Inventory, InventoryMovement, Product, Store
from app.services.inventory import (
    ADJUSTMENT,
    PURCHASE,
    SALE,
    BatchService,
    InventoryService,
)
from app.services.inventory.errors import (
    BatchMismatchError,
    DuplicateBatchError,
    EntityNotFoundError,
    ValidationError,
)

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
    s = Store(name="Domain Store", timezone="Asia/Kolkata")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@pytest.fixture()
def product(db, store) -> Product:
    p = Product(store_id=store.id, sku="COMPLAN", name="Complan", selling_price=150)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _batch_service(db):
    return BatchService(db)


def _inv_service(db):
    return InventoryService(db)


# ---------------------------------------------------------------------------
# 1-5. Batch creation + validation
# ---------------------------------------------------------------------------
def test_create_batch_with_full_metadata(db, store, product):
    bs = _batch_service(db)
    b = bs.create_batch(
        store_id=store.id,
        product_id=product.id,
        batch_number="B1",
        manufacturing_date=date(2026, 1, 10),
        expiry_date=date(2026, 12, 31),
        mrp=Decimal("150.00"),
        quantity=0,
    )
    assert b.batch_number == "B1"
    assert b.manufacturing_date == date(2026, 1, 10)
    assert b.expiry_date == date(2026, 12, 31)
    assert b.expiry_date_precision == "day"
    assert b.mrp == Decimal("150.00")


def test_create_batch_without_optional_expiry(db, store, product):
    bs = _batch_service(db)
    b = bs.create_batch(
        store_id=store.id, product_id=product.id, batch_number="NOEXP"
    )
    assert b.batch_number == "NOEXP"
    assert b.expiry_date is None
    assert b.manufacturing_date is None
    assert b.mrp is None


def test_create_batch_with_month_precision(db, store, product):
    bs = _batch_service(db)
    b = bs.create_batch(
        store_id=store.id,
        product_id=product.id,
        batch_number="MONTH",
        expiry_date=date(2027, 9, 1),
        expiry_date_precision="month",
    )
    assert b.expiry_date_precision == "month"
    assert b.expiry_date == date(2027, 9, 1)


def test_reject_invalid_dates(db, store, product):
    bs = _batch_service(db)
    # Non-date value for a date field is rejected.
    with pytest.raises(ValidationError):
        bs.create_batch(store_id=store.id, product_id=product.id, batch_number="X",
                        expiry_date="2026-02-30")  # string, not a date


def test_reject_expiry_before_manufacturing(db, store, product):
    bs = _batch_service(db)
    with pytest.raises(ValidationError):
        bs.create_batch(
            store_id=store.id, product_id=product.id, batch_number="BAD",
            manufacturing_date=date(2026, 6, 1), expiry_date=date(2026, 1, 1),
        )


def test_reject_negative_mrp(db, store, product):
    bs = _batch_service(db)
    with pytest.raises(ValidationError):
        bs.create_batch(store_id=store.id, product_id=product.id,
                        batch_number="NEG", mrp=Decimal("-1"))


def test_reject_invalid_precision(db, store, product):
    bs = _batch_service(db)
    with pytest.raises(ValidationError):
        bs.create_batch(store_id=store.id, product_id=product.id,
                        batch_number="P", expiry_date_precision="fortnight")


# ---------------------------------------------------------------------------
# 6-8. Multiple batches / uniqueness
# ---------------------------------------------------------------------------
def test_product_can_have_multiple_batches(db, store, product):
    bs = _batch_service(db)
    bs.create_batch(store_id=store.id, product_id=product.id, batch_number="A")
    bs.create_batch(store_id=store.id, product_id=product.id, batch_number="B")
    bs.create_batch(store_id=store.id, product_id=product.id, batch_number="C")
    assert len(bs.get_batches_for_product(store.id, product.id)) == 3


def test_same_batch_number_for_different_products(db, store):
    p1 = Product(store_id=store.id, sku="P1", name="P1", selling_price=1)
    p2 = Product(store_id=store.id, sku="P2", name="P2", selling_price=2)
    db.add_all([p1, p2])
    db.commit()
    db.refresh(p1)
    db.refresh(p2)
    bs = _batch_service(db)
    bs.create_batch(store_id=store.id, product_id=p1.id, batch_number="SHARED")
    # same number, different product -> allowed
    bs.create_batch(store_id=store.id, product_id=p2.id, batch_number="SHARED")


def test_duplicate_batch_constraint(db, store, product):
    bs = _batch_service(db)
    bs.create_batch(store_id=store.id, product_id=product.id, batch_number="DUP")
    with pytest.raises(DuplicateBatchError):
        bs.create_batch(store_id=store.id, product_id=product.id, batch_number="DUP")


def test_same_batch_number_for_different_store(db, product):
    store2 = Store(name="Another Store", timezone="Asia/Kolkata")
    db.add(store2)
    db.commit()
    db.refresh(store2)
    assert store2.id != product.store_id
    bs = _batch_service(db)
    bs.create_batch(store_id=product.store_id, product_id=product.id, batch_number="S1")
    # same number under a different store -> allowed
    bs.create_batch(store_id=store2.id, product_id=product.id, batch_number="S1")


def test_null_batch_number_rows_coexist(db, store, product):
    bs = _batch_service(db)
    bs.create_batch(store_id=store.id, product_id=product.id, batch_number=None, quantity=5)
    # NULL batch_number is distinct per row -> a second NULL batch is allowed
    bs.create_batch(store_id=store.id, product_id=product.id, batch_number=None, quantity=7)
    batches = bs.get_batches_for_product(store.id, product.id)
    assert len(batches) == 2


def test_entity_required(db):
    bs = _batch_service(db)
    fake = UUID(int=1)
    with pytest.raises(EntityNotFoundError):
        bs.create_batch(store_id=fake, product_id=fake, batch_number="NOPE")


# ---------------------------------------------------------------------------
# 9-14. Stock / movements / atomicity
# ---------------------------------------------------------------------------
def test_receive_stock_creates_movement_and_updates_both(db, store, product):
    bs = _batch_service(db)
    b = bs.create_batch(store_id=store.id, product_id=product.id, batch_number="RECV")
    isv = _inv_service(db)
    movement = isv.receive_stock(
        store_id=store.id, product_id=product.id, quantity_change=20,
        batch_id=b.id, reference="PO-1",
    )
    assert movement.movement_type == PURCHASE
    assert movement.batch_id == b.id
    assert isv.get_product_inventory(store.id, product.id).quantity == 20
    assert isv.get_batch_inventory(store.id, product.id)[0].quantity == 20


def test_receive_stock_by_batch_number(db, store, product):
    bs = _batch_service(db)
    bs.create_batch(store_id=store.id, product_id=product.id, batch_number="B2")
    isv = _inv_service(db)
    isv.receive_stock(store_id=store.id, product_id=product.id, quantity_change=5,
                      batch_number="B2")
    assert isv.get_product_inventory(store.id, product.id).quantity == 5


def test_inventory_movement_records_batch_reference(db, store, product):
    bs = _batch_service(db)
    b = bs.create_batch(store_id=store.id, product_id=product.id, batch_number="MOVE")
    isv = _inv_service(db)
    mv = isv.record_movement(
        store_id=store.id, product_id=product.id, quantity_change=+2,
        movement_type=PURCHASE, batch_id=b.id, reference="X",
    )
    assert db.get(InventoryMovement, mv.id).batch_id == b.id


def test_inventory_and_movement_transaction_atomic(db, store, product):
    """A single operation updates Inventory + movement together."""
    bs = _batch_service(db)
    b = bs.create_batch(store_id=store.id, product_id=product.id, batch_number="ATOM")
    isv = _inv_service(db)
    isv.receive_stock(store_id=store.id, product_id=product.id, quantity_change=10,
                      batch_id=b.id)
    inv = isv.get_product_inventory(store.id, product.id)
    movements = db.query(InventoryMovement).filter_by(product_id=product.id).count()
    assert inv.quantity == 10
    assert movements == 1


def test_failed_transaction_rolls_back(db, store, product):
    bs = _batch_service(db)
    isv = _inv_service(db)
    # Operation that fails validation must not mutate Inventory.
    with pytest.raises(ValidationError):
        isv.adjust_stock(store_id=store.id, product_id=product.id, quantity_change=0)
    assert db.query(Inventory).filter_by(product_id=product.id).count() == 0
    assert db.query(InventoryMovement).filter_by(product_id=product.id).count() == 0

    # A batch-scoped operation referencing a non-existent batch rolls back.
    with pytest.raises(EntityNotFoundError):
        isv.receive_stock(store_id=store.id, product_id=product.id,
                          quantity_change=100, batch_number="GHOST")
    assert db.query(Inventory).filter_by(product_id=product.id).count() == 0
    assert db.query(InventoryMovement).filter_by(product_id=product.id).count() == 0


def test_batch_specific_inventory_sums_to_aggregate(db, store, product):
    bs = _batch_service(db)
    isv = _inv_service(db)
    bs.create_batch(store_id=store.id, product_id=product.id, batch_number="SUM-A")
    bs.create_batch(store_id=store.id, product_id=product.id, batch_number="SUM-B")
    isv.receive_stock(store_id=store.id, product_id=product.id, quantity_change=20,
                      batch_number="SUM-A")
    isv.receive_stock(store_id=store.id, product_id=product.id, quantity_change=30,
                      batch_number="SUM-B")
    agg, batches = isv.get_product_batch_summary(store.id, product.id)
    assert agg == 50
    assert sum(b.quantity for b in batches) == 50


def test_batch_mismatch_rejected(db, store, product):
    bs = _batch_service(db)
    b = bs.create_batch(store_id=store.id, product_id=product.id, batch_number="OWN")
    other = Product(store_id=store.id, sku="OTHER", name="Other", selling_price=1)
    db.add(other)
    db.commit()
    db.refresh(other)
    isv = _inv_service(db)
    with pytest.raises(BatchMismatchError):
        isv.receive_stock(store_id=store.id, product_id=other.id, quantity_change=1,
                          batch_id=b.id)


def test_sale_and_return_movements_reference_batch(db, store, product):
    bs = _batch_service(db)
    isv = _inv_service(db)
    bs.create_batch(store_id=store.id, product_id=product.id, batch_number="SALE-1")
    isv.receive_stock(store_id=store.id, product_id=product.id, quantity_change=20,
                      batch_number="SALE-1")
    sale = isv.record_movement(store_id=store.id, product_id=product.id,
                               quantity_change=-2, movement_type=SALE, batch_number="SALE-1")
    ret = isv.record_movement(store_id=store.id, product_id=product.id,
                              quantity_change=+1, movement_type="RETURN", batch_number="SALE-1")
    assert sale.batch_id is not None and ret.batch_id is not None
    assert isv.get_product_inventory(store.id, product.id).quantity == 19
    assert isv.get_batch_inventory(store.id, product.id)[0].quantity == 19


def test_no_fefo_batch_selection_in_domain(db, store, product):
    # There is no auto batch-selection API; a batch must always be explicit.
    isv = _inv_service(db)
    method = getattr(isv, "select_batch_for_sale", None)
    assert method is None, "FEFO/auto batch selection must not exist yet"