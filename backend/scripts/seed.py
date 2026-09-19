"""Seed script for the Storeye dev database.

Creates a demo Store with zones, shelves, products, inventory, a
planogram, a customer, a sale and a bill, plus matching inventory
movements. Idempotent: safe to re-run against the same store.

Run from the backend/ directory:
    python -m scripts.seed
It uses DATABASE_URL (env) or the default dev URL.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.db.base import Base
from app.db.session import create_db_engine
from app.core.auth import hash_password
from sqlalchemy.orm import Session
from app.models import (
    Batch,
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

DEMO_STORE_NAME = "Storeye Demo Kirana"

# Bootstrap login for a freshly seeded (non-demo) dev database. Owners
# provision further users through POST /api/users after logging in.
SEED_OWNER_EMAIL = "owner@storeye.local"
SEED_OWNER_PASSWORD = "StoreyeOwner@123"


def seed(database_url: str | None = None) -> bool:
    engine = create_db_engine(database_url)
    Base.metadata.create_all(engine)  # ensure schema exists if migrations not run

    with Session(engine) as session:
        # Upsert-by-name for the demo store.
        store = _get_or_create_store(session)

        # Zones
        zone_a = _get_or_create(session, Zone, store_id=store.id, name="Snacks")
        zone_b = _get_or_create(session, Zone, store_id=store.id, name="Beverages")

        # Shelves
        shelf_a1 = _get_or_create(session, Shelf, store_id=store.id, zone_id=zone_a.id, code="A1")
        shelf_a2 = _get_or_create(session, Shelf, store_id=store.id, zone_id=zone_a.id, code="A2")
        shelf_b1 = _get_or_create(session, Shelf, store_id=store.id, zone_id=zone_b.id, code="B1")

        # Products
        products = {
            "P-001": ("Lays Chips Masala", "Lays", "Snacks", "unit", Decimal("10.00"), Decimal("7.00"), "8901491101837", ["Lays", "chips packet", "snack packet"]),
            "P-002": ("Maggi 2-Minute Noodles", "Nestle", "Instant Food", "unit", Decimal("14.00"), Decimal("10.50"), "8901057200233", ["Maggi", "noodles", "food packet"]),
            "P-003": ("Pepsi 750ml", "PepsiCo", "Beverages", "unit", Decimal("40.00"), Decimal("30.00"), "8901735060182", ["Pepsi", "bottle"]),
            "P-004": ("Haldiram Namkeen", "Haldiram", "Snacks", "unit", Decimal("25.00"), Decimal("18.00"), "8904063200058", ["Haldiram", "namkeen", "snack packet"]),
            "P-005": ("Parle-G Biscuits", "Parle", "Biscuits", "unit", Decimal("10.00"), Decimal("8.00"), "8901064130006", ["ParleG", "biscuit packet"]),
            "P-006": ("Amul Milk 1L", "Amul", "Dairy", "litre", Decimal("62.00"), Decimal("52.00"), "8901262030003", ["AmulMilk", "milk carton", "carton"]),
        }
        product_ids = {}
        for sku, (name, brand, cat, unit_, price, cost, barcode, ai_classes) in products.items():
            prod = (
                session.query(Product)
                .filter(Product.store_id == store.id, Product.sku == sku)
                .first()
            )
            if prod is None:
                prod = Product(
                    store_id=store.id,
                    sku=sku,
                    name=name,
                    brand=brand,
                    category=cat,
                    unit=unit_,
                    selling_price=price,
                    cost_price=cost,
                    barcode=barcode,
                    ai_classes=ai_classes,
                )
                session.add(prod)
                session.flush()
            else:
                prod.barcode = barcode
                prod.ai_classes = ai_classes
            product_ids[sku] = prod.id

        # Inventory + movements
        inv_qty = {sku: q for sku, q in [("P-001", 120), ("P-002", 80), ("P-003", 60), ("P-004", 45), ("P-005", 50), ("P-006", 40)]}
        for sku, qty in inv_qty.items():
            prod_id = product_ids[sku]
            inv = (
                session.query(Inventory)
                .filter(Inventory.store_id == store.id, Inventory.product_id == prod_id)
                .first()
            )
            if inv is None:
                inv = Inventory(store_id=store.id, product_id=prod_id, quantity=qty, reorder_level=10, reorder_quantity=50)
                session.add(inv)
                session.flush()
                session.add(InventoryMovement(store_id=store.id, product_id=prod_id, quantity_change=qty, movement_type="PURCHASE", reference="SEED-OPENING"))

        # Batches with realistic expiry dates
        from datetime import timedelta

        def _rel_d(days: int):
            return date.today() + timedelta(days=days)

        seed_batches = {
            "P-001": [("LAYS-B1", _rel_d(5), 20), ("LAYS-B2", _rel_d(120), 100)],
            "P-002": [("MAGGI-B1", _rel_d(-3), 8), ("MAGGI-B2", _rel_d(180), 72)],
            "P-003": [("PEPSI-B1", _rel_d(60), 60)],
            "P-004": [("HALD-B1", _rel_d(18), 15), ("HALD-B2", _rel_d(150), 30)],
            "P-005": [("PARLE-B1", _rel_d(180), 50)],
            "P-006": [("AMUL-B1", _rel_d(-2), 4), ("AMUL-B2", _rel_d(4), 10), ("AMUL-B3", _rel_d(20), 26)],
        }
        for sku, blist in seed_batches.items():
            if sku not in product_ids:
                continue
            pid = product_ids[sku]
            for bnum, bexp, bqty in blist:
                existing = (
                    session.query(Batch)
                    .filter(
                        Batch.store_id == store.id,
                        Batch.product_id == pid,
                        Batch.batch_number == bnum,
                    )
                    .first()
                )
                if existing is None:
                    session.add(
                        Batch(
                            store_id=store.id,
                            product_id=pid,
                            batch_number=bnum,
                            expiry_date=bexp,
                            expiry_date_precision="day",
                            quantity=bqty,
                        )
                    )
                else:
                    existing.expiry_date = bexp
                    existing.quantity = bqty
        session.flush()

        # Camera
        camera = (
            session.query(Camera).filter(Camera.store_id == store.id, Camera.name == "Entrance Cam").first()
        )
        if camera is None:
            session.add(Camera(store_id=store.id, name="Entrance Cam", location="Main Entrance", camera_type="usb", is_active=True))

        # Planogram + items
        planogram = (
            session.query(Planogram).filter(Planogram.store_id == store.id, Planogram.name == "Default Layout").first()
        )
        if planogram is None:
            planogram = Planogram(store_id=store.id, name="Default Layout", is_active=True)
            session.add(planogram)
            session.flush()
            shelf_map = {"P-001": shelf_a1.id, "P-002": shelf_a2.id, "P-003": shelf_b1.id, "P-004": shelf_a1.id}
            for sku, shelf_id in shelf_map.items():
                if sku == "P-004":
                    continue  # P-004 shares shelf A1; keep a tidy 3-item planogram
                session.add(PlanogramItem(planogram_id=planogram.id, shelf_id=shelf_id, product_id=product_ids[sku], expected_facings=5, minimum_facings=2, maximum_facings=8))

        # Customer
        customer = (
            session.query(Customer).filter(Customer.store_id == store.id, Customer.mobile == "9876500000").first()
        )
        if customer is None:
            customer = Customer(store_id=store.id, mobile="9876500000", name="Amit Sharma")
            session.add(customer)
            session.flush()

        # Sale + bill (sample transaction)
        sale = (
            session.query(Sale).filter(Sale.store_id == store.id).first()
        )
        if sale is None:
            sale = Sale(store_id=store.id, subtotal=Decimal("64.00"), tax_total=Decimal("0.00"), total=Decimal("64.00"), payment_method="cash", customer_id=customer.id)
            session.add(sale)
            session.flush()
            items = [
                (product_ids["P-001"], 2, Decimal("10.00")),
                (product_ids["P-002"], 3, Decimal("14.00")),
            ]
            for prod_id, qty, price in items:
                session.add(SaleItem(sale_id=sale.id, product_id=prod_id, quantity=qty, unit_price=price, line_total=price * qty))
            session.add(Bill(store_id=store.id, bill_number="BILL-0001", sale_id=sale.id, customer_id=customer.id, subtotal=Decimal("64.00"), tax_total=Decimal("0.00"), total=Decimal("64.00"), delivery_status="PENDING"))
            # decrement inventory for sale
            for prod_id, qty, _price in items:
                inv = session.query(Inventory).filter(Inventory.store_id == store.id, Inventory.product_id == prod_id).first()
                if inv:
                    inv.quantity -= qty
                    session.add(InventoryMovement(store_id=store.id, product_id=prod_id, quantity_change=-qty, movement_type="SALE", reference="BILL-0001"))

        # Demo Biscuit product + two batches (Milestone 7). Idempotent:
        # create each batch only once; receive stock only upon creation.
        demo_biscuit = (
            session.query(Product)
            .filter(Product.store_id == store.id, Product.sku == "BISC")
            .first()
        )
        if demo_biscuit is None:
            demo_biscuit = Product(
                store_id=store.id, sku="BISC", name="Demo Biscuit",
                brand="Storeye Labs", category="Bakery", unit="pack",
                selling_price=Decimal("20.00"), cost_price=Decimal("14.00"),
            )
            session.add(demo_biscuit)
            session.flush()
            session.add(Inventory(store_id=store.id, product_id=demo_biscuit.id, quantity=0, reorder_level=5, reorder_quantity=25))

        from app.services.inventory import BatchService, InventoryService
        bs = BatchService(session)
        isv = InventoryService(session)
        for batch_num, exp, qty in [
            ("BISC001", date(2026, 12, 31), 10),
            ("BISC002", date(2027, 6, 30), 20),
        ]:
            existing = bs.get_batch(store_id=store.id, product_id=demo_biscuit.id, batch_number=batch_num)
            if existing is None:
                bs.create_batch(
                    store_id=store.id,
                    product_id=demo_biscuit.id,
                    batch_number=batch_num,
                    expiry_date=exp,
                    expiry_date_precision="day",
                    quantity=0,
                )
                # receive the batch's opening stock atomically
                isv.receive_stock(
                    store_id=store.id,
                    product_id=demo_biscuit.id,
                    quantity_change=qty,
                    batch_number=batch_num,
                    reference="SEED-OPENING",
                )

        # Bootstrap owner user (idempotent by email).
        owner = (
            session.query(User)
            .filter(User.email == SEED_OWNER_EMAIL)
            .first()
        )
        if owner is None:
            owner = User(
                store_id=store.id,
                name="Store Owner",
                mobile="9800000000",
                role="OWNER",
                email=SEED_OWNER_EMAIL,
                password_hash=hash_password(SEED_OWNER_PASSWORD),
                is_active=True,
            )
            session.add(owner)
            session.flush()

        session.commit()
        return session.query(Store).filter(Store.name == DEMO_STORE_NAME).scalar() is not None


def _get_or_create_store(session):
    store = session.query(Store).filter(Store.name == DEMO_STORE_NAME).first()
    if store is None:
        store = Store(name=DEMO_STORE_NAME, address="12 MG Road", city="Bengaluru", phone="080-12345678", timezone="Asia/Kolkata")
        session.add(store)
        session.flush()
    return store


def _get_or_create(session, model, **kwargs):
    obj = session.query(model).filter_by(**kwargs).first()
    if obj is None:
        obj = model(**kwargs)
        session.add(obj)
        session.flush()
    return obj


if __name__ == "__main__":
    url = os.getenv("DATABASE_URL")
    seed(url)
    print("Seeding complete for", DEMO_STORE_NAME)