"""Tests for the Storeye PostgreSQL data & inventory layer."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import (
    Bill,
    Camera,
    Customer,
    Inventory,
    InventoryMovement,
    Planogram,
    PlanogramItem,
    Product,
    Sale,
    SaleItem,
    Shelf,
    Store,
    User,
    Zone,
)

pytestmark = pytest.mark.pg

# Tests run against an isolated PostgreSQL database so production data is
# never touched. Override here so it also works when the env is unset.
TEST_DB_URL = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg2://storeye@localhost:5433/storeye_test")


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DB_URL)
    Base.metadata.create_all(eng)
    yield eng
    # Drop all tables created by tests at the end of the session.
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def db(engine):
    """Fresh, empty tables for each test (truncate style)."""
    with engine.begin() as conn:
        Base.metadata.drop_all(conn)
        Base.metadata.create_all(conn)
    session = Session(engine)
    yield session
    session.close()


def _make_store(session) -> Store:
    store = Store(name="Test Store", timezone="Asia/Kolkata")
    session.add(store)
    session.commit()
    session.refresh(store)
    return store


def _make_product(session, store_id, sku="SKU-1", name="Test Product") -> Product:
    p = Product(store_id=store_id, sku=sku, name=name, selling_price=10)
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


def test_store_and_user_crud(db):
    store = _make_store(db)
    assert store.id is not None
    user = User(store_id=store.id, name="Owner", role="OWNER")
    db.add(user)
    db.commit()
    db.refresh(user)
    assert user.store_id == store.id
    assert user.created_at is not None
    assert user.updated_at is not None


def test_product_inventory_chain(db):
    store = _make_store(db)
    product = _make_product(db, store.id, sku="CHIPS", name="Chips")
    inv = Inventory(store_id=store.id, product_id=product.id, quantity=50, reorder_level=10, reorder_quantity=30)
    db.add(inv)
    db.commit()
    db.refresh(inv)
    assert inv.quantity == 50

    db.add(InventoryMovement(store_id=store.id, product_id=product.id, quantity_change=-4, movement_type="SALE", reference="BILL-1"))
    db.commit()
    moves = db.query(InventoryMovement).filter_by(product_id=product.id).all()
    assert len(moves) == 1
    assert moves[0].quantity_change == -4


def test_unique_product_sku_per_store(db):
    store = _make_store(db)
    _make_product(db, store.id, sku="SKU-DUP", name="A")
    with pytest.raises(Exception):
        p = Product(store_id=store.id, sku="SKU-DUP", name="B")
        db.add(p)
        db.commit()


def test_cascade_delete_store_removes_products(db):
    store = _make_store(db)
    product = _make_product(db, store.id)
    db.add(Inventory(store_id=store.id, product_id=product.id, quantity=5))
    db.commit()
    db.delete(store)
    db.commit()
    assert db.query(Product).filter_by(store_id=store.id).count() == 0


def test_zone_shelf_planogram_bill_flow(db):
    store = _make_store(db)
    zone = Zone(store_id=store.id, name="Snacks")
    db.add(zone)
    db.commit()
    db.refresh(zone)
    shelf = Shelf(store_id=store.id, zone_id=zone.id, code="A1")
    db.add(shelf)
    db.commit()
    db.refresh(shelf)
    assert db.query(Shelf).filter_by(code="A1").count() == 1

    product = _make_product(db, store.id, sku="MAGGI", name="Maggi")
    planogram = Planogram(store_id=store.id, name="Main")
    db.add(planogram)
    db.commit()
    db.refresh(planogram)
    db.add(PlanogramItem(planogram_id=planogram.id, shelf_id=shelf.id, product_id=product.id, expected_facings=5, minimum_facings=2, maximum_facings=8))
    db.commit()
    assert db.query(PlanogramItem).filter_by(planogram_id=planogram.id).count() == 1

    customer = Customer(store_id=store.id, mobile="9123456789", name="Rahul")
    db.add(customer)
    db.commit()
    db.refresh(customer)

    sale = Sale(store_id=store.id)
    db.add(sale)
    db.commit()
    db.refresh(sale)
    db.add(SaleItem(sale_id=sale.id, product_id=product.id, quantity=3, unit_price=14, line_total=42))
    db.commit()

    db.add(Bill(store_id=store.id, bill_number="BILL-900", sale_id=sale.id, customer_id=customer.id, delivery_status="PENDING"))
    db.commit()
    assert db.query(Bill).filter_by(bill_number="BILL-900").count() == 1


def test_camera_and_unique_shelf_code(db):
    store = _make_store(db)
    zone = Zone(store_id=store.id, name="Zone")
    db.add(zone)
    db.commit()
    db.refresh(zone)
    db.add(Shelf(store_id=store.id, zone_id=zone.id, code="B1"))
    db.add(Camera(store_id=store.id, name="Cam", location="Entrance", camera_type="usb"))
    db.commit()