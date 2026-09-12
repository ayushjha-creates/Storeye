"""Seed the Storeye DEMO store with deterministic, idempotent showcase data.

This is the M18 "Demo Showcase Mode" dataset. Every row uses a fixed, stable
UUID (uuid5 over the storeye-demo namespace) so re-runs never duplicate rows.
The dataset is deliberately synthetic and deterministic:

    * a single demo store ("Storeye Demo Mart", New Delhi)
    * four shelf regions (A1, A2, B1, B2) on one camera with an active planogram
    * REAL Edge-AI-shaped observations driving product + shelf intelligence,
      misplacement foundation, people counts and AI-summary numbers
    * realistic inventory with batches (healthy / soon-to-expire / expired),
      low-stock and out-of-stock rows
    * a week of sales + bills and a couple of customers
    * alerts covering every lifecycle stage (OPEN / ACKNOWLEDGED / RESOLVED)
      created through the real AlertService (dedup + transitions respected)
    * persisted reconciliation snapshots within the 24h window

Invariants respected:
    * stock is only mutated through InventoryService.receive_stock (or the
      direct opening adjustments shown by the standard seed), never by AI
    * batches described by Batch.status / expiries are the real Batch rows
    * alert timestamps/states go through AlertService transitions
    * everything is labeled demo data by the frontend, never presented as truth

Run (from the backend/ directory):
    python -m scripts.seed_demo                # idempotent seed
    python -m scripts.seed_demo --reset        # delete + reseed the demo store
"""

from __future__ import annotations

import os
import sys
import uuid
import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import create_db_engine
from app.models import (
    ALERT_CAMERA_OFFLINE,
    ALERT_EXPIRY,
    ALERT_LOW_SHELF_OCCUPANCY,
    ALERT_MISPLACEMENT,
    ALERT_REVIEW_REQUIRED,
    ALERT_SHORTAGE,
    ALERT_SURPLUS,
    OBS_PERSON,
    OBS_PRODUCT,
    REC_MATCH,
    REC_REVIEW,
    REC_SHORTAGE,
    REC_SURPLUS,
    SEV_CRITICAL,
    SEV_HIGH,
    SEV_LOW,
    SEV_MEDIUM,
    STATUS_ACKNOWLEDGED,
    STATUS_RESOLVED,
    Alert,
    Batch,
    Bill,
    Camera,
    Customer,
    Inventory,
    InventoryMovement,
    Observation,
    Planogram,
    PlanogramItem,
    Product,
    ReconciliationResult,
    Sale,
    SaleItem,
    Shelf,
    Store,
    User,
    Zone,
)
from app.services.alerts import AlertService
from app.services.inventory import BatchService, InventoryService

DEMO_STORE_NAME = "Storeye Demo Mart"


def fixed(slug: str) -> uuid.UUID:
    """Deterministic identity for demo rows (stable across machines/runs)."""
    return uuid.uuid5(uuid.NAMESPACE_URL, "storeye-demo/" + slug)


def _d(y: int, m: int, d: int):
    """Local date helper (timezone-free) for batch expiries."""
    import datetime as _dt

    return _dt.date(y, m, d)


# ---------------------------------------------------------------------------
# Demo dataset table
# ---------------------------------------------------------------------------

# (sku, name, brand, category, unit, price, cost, barcode, ai_classes)
PRODUCTS: List[Tuple[str, str, str, str, str, float, float, str, List[str]]] = [
    ("AAS-ATTA", "Aashirvaad Atta 5kg", "ITC", "Atta & Flours", "pack", 240.00, 200.00, "8901063001015", ["Aashirvaad"]),
    ("TATA-SALT", "Tata Salt 1kg", "Tata Consumer", "Staples", "pack", 28.00, 20.00, "8900000000012", ["TataSalt"]),
    ("AMUL-MILK", "Amul Milk 1L", "Amul", "Dairy", "litre", 62.00, 52.00, "8901262030003", ["AmulMilk"]),
    ("BRIT-BREAD", "Britannia Bread 400g", "Britannia", "Bakery", "unit", 45.00, 35.00, "8901154000003", []),
    ("PARLE-G", "Parle-G Biscuits", "Parle", "Biscuits", "pack", 10.00, 8.00, "8901064130006", ["ParleG"]),
    ("FORT-OIL", "Fortune Sunflower Oil 1L", "Fortune", "Oils", "litre", 175.00, 155.00, "8906019070004", ["Fortune"]),
    ("MAGGI-2MIN", "Maggi 2-Minute Noodles", "Nestle", "Instant Food", "pack", 14.00, 10.00, "8901057200233", ["Maggi"]),
    ("SURF-MATIC", "Surf Excel Matic 1kg", "HUL", "Home Care", "pack", 240.00, 205.00, "8901030916472", []),
    ("COKE-750", "Coca-Cola 750ml", "Coca-Cola", "Beverages", "unit", 40.00, 30.00, "8901764001415", []),
    ("PEPSI-750", "Pepsi 750ml", "PepsiCo", "Beverages", "unit", 40.00, 30.00, "8901735060182", ["Pepsi"]),
    ("FORT-RICE", "Fortune Basmati Rice 5kg", "Fortune", "Grains", "pack", 420.00, 380.00, "8906002380002", []),
    ("AMUL-BUTTER", "Amul Butter 500g", "Amul", "Dairy", "pack", 265.00, 240.00, "8901262030538", []),
    ("NESCAFE", "Nescafe Classic 100g", "Nestle", "Beverages", "unit", 190.00, 165.00, "8901052520020", []),
    ("DAIRY-MILK", "Cadbury Dairy Milk 53g", "Mondelez", "Confectionery", "unit", 30.00, 24.00, "8901234000650", []),
]

# sku -> (target quantity, reorder_level, reorder_quantity) for products that
# have an Inventory row. PEPSI deliberately has NO row (NO_INVENTORY demo).
INVENTORY: Dict[str, Tuple[int, int, int]] = {
    "AAS-ATTA": (60, 80, 100),
    "TATA-SALT": (60, 100, 120),
    "AMUL-MILK": (18, 25, 40),
    "BRIT-BREAD": (0, 12, 24),
    "PARLE-G": (18, 15, 60),
    "FORT-OIL": (48, 25, 60),
    "MAGGI-2MIN": (10, 15, 40),
    "SURF-MATIC": (30, 40, 60),
    "COKE-750": (60, 60, 96),
    "FORT-RICE": (50, 60, 40),
    "AMUL-BUTTER": (16, 8, 24),
    "NESCAFE": (14, 6, 12),
    "DAIRY-MILK": (22, 20, 60),
}

# sku -> [(batch_number, expiry date, quantity)] — batch-scoped stock.
BATCHES: Dict[str, List[Tuple[str, "datetime.date", int]]] = {
    "AMUL-MILK": [
        ("AMUL-1", _d(2026, 8, 20), 4),  # EXPIRED (demo)
        ("AMUL-2", _d(2026, 10, 7), 6),  # expiring within 30 days
        ("AMUL-3", _d(2027, 6, 15), 8),  # healthy
    ],
    "AAS-ATTA": [
        ("AAS-1", _d(2026, 10, 5), 60),  # expiring within 30 days
    ],
    "FORT-OIL": [
        ("FORT-1", _d(2027, 3, 1), 36),
        ("FORT-2", _d(2027, 9, 1), 12),
    ],
}

# Camera config: shelf regions in normalized [0,100] camera space. Stripes are
# deliberately non-overlapping so product->shelf association is unambiguous.
SHELF_REGIONS = [
    {"code": "A1", "label": "A1 · Snacks (top)", "bbox": [5, 14, 95, 34]},
    {"code": "A2", "label": "A2 · Snacks (lower)", "bbox": [5, 40, 95, 54]},
    {"code": "B1", "label": "B1 · Beverages (upper)", "bbox": [5, 58, 95, 72]},
    {"code": "B2", "label": "B2 · Beverages (lower)", "bbox": [5, 78, 95, 96]},
    {"code": "E1", "label": "E1 · End-cap display", "bbox": [5, 2, 95, 12]},
]

# Planogram expectations: shelf code -> [sku, ...]
PLANOGRAM = {
    "A1": ["AAS-ATTA", "PARLE-G"],
    "A2": ["MAGGI-2MIN"],
    "B1": ["TATA-SALT", "FORT-OIL", "COKE-750"],
    "B2": ["AMUL-MILK", "COKE-750"],
}

# AI observations per class: (class, camera_name, bbox, count). Regions decide
# shelf association / occupancy; boxes fully outside a region => "Shelf: Unknown".
CLASS_OBSERVATIONS = [
    # A1 -> NORMAL visible occupancy; Aashirvaad below reorder level.
    ("Aashirvaad", "Demo Shelf Camera", [10, 16, 44, 32], 8),
    ("ParleG", "Demo Shelf Camera", [50, 16, 58, 32], 18),
    # A2 -> LOW visible occupancy (small footprint, Maggi only here).
    ("Maggi", "Demo Shelf Camera", [70, 42, 76, 52], 6),
    # B1 -> NORMAL occupancy; Fortune + Tata Salt on-planogram.
    ("Fortune", "Demo Shelf Camera", [16, 60, 20, 70], 48),
    ("TataSalt", "Demo Shelf Camera", [30, 60, 35, 70], 72),
    # B2 -> NORMAL occupancy; Amul Milk on-planogram, Maggi misplaced here.
    ("AmulMilk", "Demo Shelf Camera", [10, 80, 14, 92], 18),
    ("Maggi", "Demo Shelf Camera", [62, 80, 70, 94], 4),
    # Outside all regions (x < 5) -> "Shelf: Unknown"; Pepsi has no inventory.
    ("Pepsi", "Demo Shelf Camera", [1, 20, 4, 60], 12),
    # Unmapped AI class -> NOT_ASSESSED ("Premium Detergent Display").
    ("PremiumDetergent", "Demo Shelf Camera", [1, 64, 4, 96], 6),
]

# (day offset from today, payment_method, [(sku, qty), ...])
SALES: List[Tuple[int, str, List[Tuple[str, int]]]] = [
    (0, "upi", [("AAS-ATTA", 38), ("FORT-OIL", 50), ("SURF-MATIC", 12), ("NESCAFE", 10), ("AMUL-MILK", 29), ("PARLE-G", 47)]),
    (1, "cash", [("AAS-ATTA", 30), ("FORT-OIL", 18), ("SURF-MATIC", 6), ("AMUL-MILK", 20), ("PARLE-G", 35), ("COKE-750", 10)]),
    (2, "upi", [("AAS-ATTA", 14), ("FORT-RICE", 8), ("TATA-SALT", 30), ("MAGGI-2MIN", 22), ("AMUL-BUTTER", 4), ("PARLE-G", 30)]),
    (3, "card", [("AMUL-MILK", 22), ("NESCAFE", 12), ("DAIRY-MILK", 10), ("COKE-750", 14)]),
    (4, "cash", [("AAS-ATTA", 16), ("FORT-OIL", 12), ("SURF-MATIC", 4), ("TATA-SALT", 24), ("PARLE-G", 25)]),
    (5, "upi", [("AMUL-MILK", 18), ("AMUL-BUTTER", 3), ("MAGGI-2MIN", 12), ("COKE-750", 8), ("DAIRY-MILK", 10)]),
    (6, "cash", [("AAS-ATTA", 12), ("TATA-SALT", 18), ("FORT-OIL", 10), ("PARLE-G", 20)]),
]

PERSON_TRACKS = {
    "Demo Entrance Cam": (1, 30),   # spread across the day
    "Demo Till Cam": (31, 42),      # recent (last ~15 minutes)
}


# ---------------------------------------------------------------------------
# ORM helpers
# ---------------------------------------------------------------------------

def _goc(session: Session, model, fixed_id: uuid.UUID, exclude: Sequence[str] = (), **lookup_kwargs):
    """Get-or-create by natural key; new rows carry a fixed deterministic id.

    `exclude` lists column names that must NOT participate in the lookup
    filter (JSON/JSONB columns cannot be compared with ``=`` in PostgreSQL).
    """
    filter_kwargs = {k: v for k, v in lookup_kwargs.items() if k not in exclude}
    obj = session.scalars(select(model).filter_by(**filter_kwargs)).first()
    if obj is None:
        obj = model(id=fixed_id, **lookup_kwargs)
        session.add(obj)
        session.flush()
    return obj


def _price_of(session: Session, store_id: uuid.UUID, sku: str) -> Decimal:
    return session.scalars(
        select(Product.selling_price).where(
            Product.store_id == store_id, Product.sku == sku
        )
    ).one()


def _movement_exists(
    session: Session,
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    reference: str,
) -> bool:
    return (
        session.scalars(
            select(InventoryMovement.id).where(
                InventoryMovement.store_id == store_id,
                InventoryMovement.product_id == product_id,
                InventoryMovement.reference == reference,
            ).limit(1)
        ).first()
        is not None
    )


def _add_observation(
    session: Session,
    *,
    camera: Camera,
    observation_type: str,
    class_name: str,
    track_id: int,
    bbox: Optional[List[float]] = None,
    confidence: float = 0.9,
    observed_at: Optional[datetime] = None,
) -> Optional[Observation]:
    """Insert an observation once (deterministic id); returns None on skip."""
    key = f"obs:{camera.id if camera else 'none'}:{observation_type}:{class_name}:{track_id}"
    existing = session.get(Observation, fixed(key))
    if existing is not None:
        return None
    now = datetime.now(timezone.utc)
    obs = Observation(
        id=fixed(key),
        store_id=camera.store_id if camera else None,
        camera_id=camera.id if camera else None,
        observation_type=observation_type,
        track_id=track_id,
        bbox=bbox,
        confidence=confidence,
        source="demo-seed",
        observed_at=observed_at or now,
        details={"class_name": class_name, "label": class_name},
    )
    session.add(obs)
    return obs


def _offset_minutes(index: int, total: int, span_minutes: int = 23 * 60) -> float:
    """Deterministic recency spread: index 0 oldest -> last newest."""
    frac = (total - index - 1) / max(total - 1, 1)
    return span_minutes * frac


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------

def seed_with_session(session: Session, now: Optional[datetime] = None) -> Dict[str, int]:
    now = now or datetime.now(timezone.utc)
    counts: Dict[str, int] = {}

    # --- Store ----------------------------------------------------------
    store = _goc(
        session, Store, fixed("store"),
        name=DEMO_STORE_NAME,
        address="G-24, Lajpat Nagar Market II",
        city="New Delhi",
        phone="011-4012-3456",
        timezone="Asia/Kolkata",
    )
    counts["stores"] = 1

    _goc(
        session, User, fixed("user:manager"),
        store_id=store.id, name="Rohan Verma", mobile="9811000000", role="Store Manager",
    )
    counts["users"] = 1

    customer_a = _goc(
        session, Customer, fixed("cust:a"),
        store_id=store.id, mobile="9899000000", name="Ananya Gupta",
    )
    customer_b = _goc(
        session, Customer, fixed("cust:b"),
        store_id=store.id, mobile="9811001122", name="Rahul Mehta",
    )
    counts["customers"] = 2

    # --- Zones + shelves (codes A1/A2/B1/B2 match camera regions) -------
    zone_snacks = _goc(
        session, Zone, fixed("zone:snacks"),
        store_id=store.id, name="Snacks",
        description="Snacks, biscuits & instant food",
    )
    zone_bev = _goc(
        session, Zone, fixed("zone:beverages"),
        store_id=store.id, name="Beverages",
        description="Cold beverages, staples & oils",
    )
    shelf_a1 = _goc(
        session, Shelf, fixed("shelf:A1"),
        store_id=store.id, zone_id=zone_snacks.id, code="A1",
        description="Aisle 1 - snacks top",
    )
    shelf_a2 = _goc(
        session, Shelf, fixed("shelf:A2"),
        store_id=store.id, zone_id=zone_snacks.id, code="A2",
        description="Aisle 1 - snacks bottom",
    )
    shelf_b1 = _goc(
        session, Shelf, fixed("shelf:B1"),
        store_id=store.id, zone_id=zone_bev.id, code="B1",
        description="Aisle 2 - beverages left",
    )
    shelf_b2 = _goc(
        session, Shelf, fixed("shelf:B2"),
        store_id=store.id, zone_id=zone_bev.id, code="B2",
        description="Aisle 2 - beverages lower",
    )
    shelf_e1 = _goc(
        session, Shelf, fixed("shelf:E1"),
        store_id=store.id, zone_id=zone_bev.id, code="E1",
        description="End-cap promotion display",
    )
    shelves = {"A1": shelf_a1, "A2": shelf_a2, "B1": shelf_b1, "B2": shelf_b2, "E1": shelf_e1}
    counts["zones"] = 2
    counts["shelves"] = 5

    # --- Products -------------------------------------------------------
    products: Dict[str, Product] = {}
    for sku, name, brand, cat, unit, price, cost, barcode, classes in PRODUCTS:
        prod = _goc(
            session, Product, fixed("prod:" + sku),
            store_id=store.id, sku=sku, name=name, brand=brand, category=cat,
            unit=unit, selling_price=Decimal(str(price)),
            cost_price=Decimal(str(cost)),
            barcode=barcode, ai_classes=classes or None,
            exclude=("ai_classes",),
        )
        products[sku] = prod
    counts["products"] = len(products)

    # --- Inventory + batches (through real services) --------------------
    batch_svc = BatchService(session)
    inv_svc = InventoryService(session)

    for sku, (qty, reorder, reorder_qty) in INVENTORY.items():
        product = products[sku]

        # Seed batches (skip when already present), then receive the opening
        # stock through InventoryService (atomic movement + quantity updates).
        batch_numbers = BATCHES.get(sku, [])
        batches_created = 0
        for batch_number, exp, bqty in batch_numbers:
            existing_batch = batch_svc.get_batch(
                store_id=store.id, product_id=product.id, batch_number=batch_number
            )
            if existing_batch is None:
                batch_svc.create_batch(
                    store_id=store.id,
                    product_id=product.id,
                    batch_number=batch_number,
                    expiry_date=exp,
                    expiry_date_precision="day",
                    quantity=0,
                )
                batches_created += 1
            if not _movement_exists(
                session, store.id, product.id, reference=f"DEMO-OPENING:{batch_number}"
            ):
                inv_svc.receive_stock(
                    store_id=store.id,
                    product_id=product.id,
                    quantity_change=bqty,
                    batch_number=batch_number,
                    reference=f"DEMO-OPENING:{batch_number}",
                )
        counts["batches"] = counts.get("batches", 0) + batches_created

        if qty > 0 and not batch_numbers:
            # Ordinary (non-batch) opening stock.
            if not _movement_exists(
                session, store.id, product.id, reference="DEMO-OPENING"
            ):
                inv_svc.receive_stock(
                    store_id=store.id,
                    product_id=product.id,
                    quantity_change=qty,
                    reference="DEMO-OPENING",
                    movement_type="PURCHASE",
                )
            inv = session.scalars(
                select(Inventory).where(
                    Inventory.store_id == store.id, Inventory.product_id == product.id
                )
            ).first()
            if inv is not None:
                inv.reorder_level = reorder
                inv.reorder_quantity = reorder_qty
        elif qty == 0:
            _goc(
                session, Inventory, fixed("inv:" + sku),
                store_id=store.id, product_id=product.id,
                quantity=0, reorder_level=reorder, reorder_quantity=reorder_qty,
            )

    # --- Cameras -----------------------------------------------
    shelf_cam = _goc(
        session, Camera, fixed("cam:shelf"),
        store_id=store.id, name="Demo Shelf Camera",
        location="Snacks & Staples Aisle",
        camera_type="file", is_active=True,
        config={
            "kind": "product",
            "product_detection": True,
            "shelf_regions": SHELF_REGIONS,
        },
        exclude=("config",),
    )
    entrance_cam = _goc(
        session, Camera, fixed("cam:entrance"),
        store_id=store.id, name="Demo Entrance Cam",
        location="Main Entrance",
        camera_type="file", is_active=True,
        config={"kind": "person", "person_detection": True},
        exclude=("config",),
    )
    till_cam = _goc(
        session, Camera, fixed("cam:till"),
        store_id=store.id, name="Demo Till Cam",
        location="Billing Counter",
        camera_type="file", is_active=True,
        config={"kind": "person", "person_detection": True},
        exclude=("config",),
    )
    roof_cam = _goc(
        session, Camera, fixed("cam:roof"),
        store_id=store.id, name="Demo Roof Cam",
        location="Store Roof / PTZ",
        camera_type="file", is_active=True,
        config={"kind": "person", "person_detection": True},
        exclude=("config",),
    )
    counts["cameras"] = 4

    # --- Planogram (active expectation) ------------------------
    planogram = _goc(
        session, Planogram, fixed("plano:default"),
        store_id=store.id, name="Demo Planogram (Active)", is_active=True,
    )
    for code, skus in PLANOGRAM.items():
        for sku in skus:
            _goc(
                session, PlanogramItem, fixed(f"plano:{code}:{sku}"),
                planogram_id=planogram.id, shelf_id=shelves[code].id,
                product_id=products[sku].id,
                expected_facings=6, minimum_facings=2, maximum_facings=10,
            )
    counts["planogram_items"] = sum(len(v) for v in PLANOGRAM.values())

    # --- AI observations ---------------------------------------
    confidence_cycle = [0.88, 0.93, 0.9, 0.96, 0.85, 0.95, 0.92, 0.97, 0.89, 0.94]
    obs_created = 0
    for entry_index, (cls, cam_name, bbox, total) in enumerate(CLASS_OBSERVATIONS):
        # Deterministic, per-entry collision-free track-id band (the same class
        # may legitimately appear on multiple shelves, each with its own band).
        band = int(hashlib.sha1(f"{cls}:{entry_index}".encode("utf-8")).hexdigest(), 16) % 4000
        for i in range(total):
            track = band + i + 1
            obs = _add_observation(
                session,
                camera=shelf_cam,
                observation_type=OBS_PRODUCT,
                class_name=cls,
                track_id=track,
                bbox=bbox,
                confidence=confidence_cycle[i % len(confidence_cycle)],
                observed_at=now - timedelta(
                    minutes=_offset_minutes(i, total) + 2
                ),
            )
            if obs is not None:
                obs_created += 1
    counts["observations"] = counts.get("observations", 0) + obs_created

    # Person tracks (entrance spread across the day, till recent).
    person_created = 0
    for cam_name, (lo, hi) in PERSON_TRACKS.items():
        cam = entrance_cam if cam_name == "Demo Entrance Cam" else till_cam
        recent = cam_name == "Demo Till Cam"
        for t in range(lo, hi + 1):
            minutes_ago = (t if recent else t * 23) % (23 * 60)
            if _add_observation(
                session,
                camera=cam,
                observation_type=OBS_PERSON,
                class_name="person",
                track_id=t,
                bbox=[t % 100, 5, t % 100 + 8, 22],
                confidence=0.9,
                observed_at=now - timedelta(minutes=minutes_ago + 1),
            ) is not None:
                person_created += 1
    counts["observations"] = counts.get("observations", 0) + person_created

    # --- Sales + bills -----------------------------------------
    sales_created = 0
    for day_offset, payment, lines in SALES:
        bill_no = f"DEMO-BILL-{day_offset + 1:04d}"
        sale_id = fixed("sale:" + bill_no)
        if session.get(Sale, sale_id) is not None:
            continue
        ts = now - timedelta(days=day_offset, hours=5)
        subtotal = sum(
            _price_of(session, store.id, sku) * Decimal(str(qty))
            for sku, qty in lines
        )
        total_qty = sum(qty for _sku, qty in lines)
        customer = customer_a if day_offset % 3 == 0 else customer_b
        sale = Sale(
            id=sale_id,
            store_id=store.id,
            customer_id=customer.id,
            subtotal=subtotal,
            tax_total=Decimal("0.00"),
            total=subtotal,
            payment_method=payment,
            sale_timestamp_utc=ts,
        )
        session.add(sale)
        session.flush()
        for sku, qty in lines:
            price = _price_of(session, store.id, sku)
            session.add(
                SaleItem(
                    id=fixed(f"sale-item:{bill_no}:{sku}"),
                    sale_id=sale.id, product_id=products[sku].id,
                    quantity=qty, unit_price=price,
                    tax=Decimal("0.00"), line_total=price * Decimal(str(qty)),
                )
            )
        session.add(
            Bill(
                id=fixed("bill:" + bill_no),
                store_id=store.id, bill_number=bill_no,
                sale_id=sale.id, customer_id=customer.id,
                subtotal=subtotal, tax_total=Decimal("0.00"), total=subtotal,
                delivery_status="DELIVERED",
            )
        )
        sales_created += 1
        total_qty  # referenced for readability only
    counts["sales"] = counts.get("sales", 0) + sales_created

    # --- Recon snapshots (persisted, informational) ------------
    recon_rows = [
        (products["AAS-ATTA"], shelf_cam, 60, 8, 0.9, REC_SHORTAGE),
        (products["TATA-SALT"], shelf_cam, 60, 72, 0.88, REC_SURPLUS),
        (products["PARLE-G"], shelf_cam, 18, 18, 0.95, REC_MATCH),
        (products["MAGGI-2MIN"], shelf_cam, 10, 10, 0.62, REC_REVIEW),
    ]
    for i, (product, cam, db_qty, ai_qty, conf, status) in enumerate(recon_rows):
        rid = fixed(f"recon:{product.sku}")
        if session.get(ReconciliationResult, rid) is not None:
            continue
        session.add(
            ReconciliationResult(
                id=rid,
                store_id=store.id, product_id=product.id, camera_id=cam.id,
                observation_window_start=now - timedelta(hours=24),
                observation_window_end=now,
                database_quantity=db_qty, ai_observed_quantity=ai_qty,
                difference=ai_qty - db_qty, status=status, confidence=conf,
                details={
                    "counting_rule": "distinct_track_ids",
                    "window_hours": 24,
                    "source": "demo-seed",
                },
            )
        )
    counts["reconciliation"] = len(recon_rows)

    # --- Alerts (through the real AlertService lifecycle) ------
    alert_svc = AlertService(session)

    def _seed_alert(
        *,
        source_id: str,
        alert_type: str,
        severity: str,
        title: str,
        message: str,
        product: Optional[Product] = None,
        shelf: Optional[Shelf] = None,
        camera: Optional[Camera] = None,
        hours_ago: float = 2,
        then: str = "open",
    ) -> int:
        existing = session.scalars(
            select(Alert).where(Alert.source_id == source_id)
        ).first()
        if existing is not None:
            return 0
        alert, _created = alert_svc.create_alert(
            store_id=store.id,
            alert_type=alert_type,
            severity=severity,
            title=title,
            message=message,
            product_id=product.id if product else None,
            shelf_id=shelf.id if shelf else None,
            camera_id=camera.id if camera else None,
            detected_at=now - timedelta(hours=hours_ago),
            source_type="demo",
            source_id=source_id,
        )
        if then == "acknowledged":
            alert_svc.acknowledge(alert, at=now - timedelta(hours=1))
        elif then == "resolved":
            alert_svc.acknowledge(alert, at=now - timedelta(hours=3))
            alert_svc.resolve(alert, at=now - timedelta(hours=2, minutes=30))
        return 1

    counts["alerts"] = (
        _seed_alert(
            source_id="demo.shortage.aashirvaad",
            alert_type=ALERT_SHORTAGE, severity=SEV_HIGH,
            title="Stock below reorder level",
            message="Aashirvaad Atta 5kg has 60 units; reorder level is 80.",
            product=products["AAS-ATTA"], hours_ago=3,
        )
        + _seed_alert(
            source_id="demo.expiry.amul.expired",
            alert_type=ALERT_EXPIRY, severity=SEV_CRITICAL,
            title="Batches past expiry (needs removal)",
            message="Amul Milk 1L batch AMUL-1 expired on 2026-08-20.",
            product=products["AMUL-MILK"], hours_ago=5,
        )
        + _seed_alert(
            source_id="demo.expiry.aashirvaad.soon",
            alert_type=ALERT_EXPIRY, severity=SEV_MEDIUM,
            title="Batches expiring within 30 days",
            message="Aashirvaad Atta 5kg batch AAS-1 expires 2026-10-05.",
            product=products["AAS-ATTA"], hours_ago=2,
        )
        + _seed_alert(
            source_id="demo.misplacement.maggi.b2",
            alert_type=ALERT_MISPLACEMENT, severity=SEV_LOW,
            title="Possible misplaced product",
            message="Maggi 2-Minute Noodles detected on Shelf B2 but "
                    "the planogram expects it on Shelf A2.",
            product=products["MAGGI-2MIN"], shelf=shelf_b2, camera=shelf_cam,
            hours_ago=1,
        )
        + _seed_alert(
            source_id="demo.low.shelf.a2",
            alert_type=ALERT_LOW_SHELF_OCCUPANCY, severity=SEV_MEDIUM,
            title="Shelf occupancy is low",
            message="Shelf A2 shows AI-estimated visible occupancy below 35%.",
            shelf=shelf_a2, camera=shelf_cam, hours_ago=2,
        )
        + _seed_alert(
            source_id="demo.camera.roof.offline",
            alert_type=ALERT_CAMERA_OFFLINE, severity=SEV_MEDIUM,
            title="No detections — camera may be offline",
            message="Demo Roof Cam produced no observations in the last 24 hours.",
            camera=roof_cam, hours_ago=6,
        )
        + _seed_alert(
            source_id="demo.surplus.tata",
            alert_type=ALERT_SURPLUS, severity=SEV_MEDIUM,
            title="Possible surplus detected",
            message="Tata Salt 1kg shows 72 AI-visible units vs 60 in inventory.",
            product=products["TATA-SALT"], hours_ago=4, then="acknowledged",
        )
        + _seed_alert(
            source_id="demo.review.maggi",
            alert_type=ALERT_REVIEW_REQUIRED, severity=SEV_LOW,
            title="Reconciliation review required",
            message="Maggi 2-Minute Noodles review flagged for manual check.",
            product=products["MAGGI-2MIN"], camera=shelf_cam, hours_ago=8,
            then="resolved",
        )
    )

    session.commit()
    return counts


def seed(database_url: Optional[str] = None) -> Dict[str, int]:
    engine = create_db_engine(database_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        return seed_with_session(session)


def reset_demo_store(session: Session) -> int:
    """Delete every demo store row (children first). Safety: only the demo
    store's own data is removed — other stores are never touched."""
    store = session.scalars(
        select(Store).where(Store.name == DEMO_STORE_NAME)
    ).first()
    if store is None:
        return 0
    store_id = store.id

    sale_ids = [x[0] for x in session.execute(
        delete(Sale).where(Sale.store_id == store_id).returning(Sale.id)
    )]

    session.execute(delete(Observation).where(Observation.store_id == store_id))
    session.execute(delete(ReconciliationResult).where(ReconciliationResult.store_id == store_id))
    session.execute(delete(Alert).where(Alert.store_id == store_id))
    session.execute(delete(InventoryMovement).where(InventoryMovement.store_id == store_id))
    session.execute(delete(Inventory).where(Inventory.store_id == store_id))
    session.execute(delete(Batch).where(Batch.store_id == store_id))
    session.execute(delete(Bill).where(Bill.store_id == store_id))
    session.execute(delete(SaleItem).where(SaleItem.sale_id.in_(sale_ids)))
    session.execute(delete(Camera).where(Camera.store_id == store_id))
    session.execute(delete(Shelf).where(Shelf.store_id == store_id))
    session.execute(delete(Zone).where(Zone.store_id == store_id))
    session.execute(delete(Product).where(Product.store_id == store_id))
    session.execute(delete(Customer).where(Customer.store_id == store_id))
    session.execute(delete(User).where(User.store_id == store_id))

    # Planogram items (children of planograms) + planograms.
    session.execute(delete(PlanogramItem).where(
        PlanogramItem.planogram_id.in_(
            select(Planogram.id).where(Planogram.store_id == store_id)
        )
    ))
    session.execute(delete(Planogram).where(Planogram.store_id == store_id))

    session.execute(delete(Store).where(Store.id == store_id))
    session.commit()
    return int(len(sale_ids))


def reset_and_seed(session: Session) -> Dict[str, int]:
    reset_demo_store(session)
    return seed_with_session(session)


if __name__ == "__main__":
    url = os.getenv("DATABASE_URL")
    engine = create_db_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        if "--reset" in sys.argv:
            print("Resetting demo store...")
            removed = reset_demo_store(session)
            print(f"Removed {removed} existing demo sales.")
        result = seed_with_session(session)
    print("Seeding complete for", DEMO_STORE_NAME, result)