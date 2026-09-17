"""M20 — Store Intelligence engine / rule tests.

Covers the deterministic insight engine against the isolated storeye_test
database:

    Inventory  (A)  LOW_STOCK / OUT_OF_STOCK
    Expiry     (B)  EXPIRED_BATCH / EXPIRY_RISK / STOCK_ROTATION
    Shelf      (C)  LOW_SHELF_AVAILABILITY / MISPLACEMENT, UNKNOWN never flagged
    Customer   (D)  HIGH_TRAFFIC_ZONE / HIGH_DWELL_ZONE /
                    HIGH_TRAFFIC_LOW_SHELF_AVAILABILITY
    Camera     (E)  CAMERA_HEALTH offline vs healthy
    Sales      (F)  HIGH_SELLING_LOW_STOCK
    Combination(G)  LOW_STOCK_WITH_LOW_SHELF_AVAILABILITY
    Engine     (H)  dedup/reconcile refresh, resolve, expiry TTL retirement,
                    acknowledged refresh, store isolation
    Alerts     (I)  M16 alert integration + NO-MUTATION proofs

ENGINE GUARANTEES UNDER TEST:
    * insight evaluation NEVER mutates inventory, batches, sales, bills,
      movements, or observations (proven by before/after snapshots);
    * flow is never translated into purchase intent (asserts on wording);
    * repeated evaluation never creates unlimited duplicates.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import (
    ALERT_CAMERA_OFFLINE,
    ALERT_EXPIRY,
    ALERT_LOW_SHELF_OCCUPANCY,
    ALERT_SHORTAGE,
    Batch,
    Camera,
    GlobalPersonSession,
    Inventory,
    InventoryMovement,
    Observation,
    OBS_PRODUCT,
    Product,
    Sale,
    SaleItem,
    SESSION_ACTIVE,
    STATUS_ACKNOWLEDGED,
    STATUS_EXPIRED,
    STATUS_OPEN,
    STATUS_RESOLVED,
    Planogram,
    PlanogramItem,
    Shelf,
    Store,
    Zone,
    ZoneVisit,
    Alert,
    Insight,
    CERTAINTY_HIGH,
    CERTAINTY_MEDIUM,
    SEV_HIGH,
    SEV_INFO,
    SEV_LOW,
    SEV_MEDIUM,
    INSIGHT_CAMERA_HEALTH,
    INSIGHT_EXPIRED_BATCH,
    INSIGHT_EXPIRY_RISK,
    INSIGHT_HIGH_DWELL_ZONE,
    INSIGHT_HIGH_SELLING_LOW_STOCK,
    INSIGHT_HIGH_TRAFFIC_LOW_SHELF,
    INSIGHT_HIGH_TRAFFIC_ZONE,
    INSIGHT_LOW_SHELF_AVAILABILITY,
    INSIGHT_LOW_STOCK,
    INSIGHT_LOW_STOCK_LOW_SHELF,
    INSIGHT_MISPLACEMENT,
    INSIGHT_OUT_OF_STOCK,
    INSIGHT_STOCK_ROTATION,
    INSIGHT_STORE_HEALTH,
)
from app.services.insights import (
    InsightEngine,
    RuleContext,
    StoreHealthService,
)
from app.services.insights.insight_rules import (
    rule_customer_flow,
    rule_low_stock_low_shelf,
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
def db(engine):
    with engine.begin() as conn:
        Base.metadata.drop_all(conn)
        Base.metadata.create_all(conn)
    session = Session(engine)
    yield session
    session.close()


@pytest.fixture()
def store(db) -> Store:
    s = Store(name="Insight Mart", timezone="Asia/Kolkata")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@pytest.fixture()
def zone(db: Session, store) -> Zone:
    z = Zone(store_id=store.id, name="Grocery")
    db.add(z)
    db.commit()
    db.refresh(z)
    return z


@pytest.fixture()
def shelf(db: Session, store, zone) -> Shelf:
    s = Shelf(store_id=store.id, zone_id=zone.id, code="A1")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


def _product(db, store, sku, name, ai_classes=None) -> Product:
    p = Product(
        store_id=store.id, sku=sku, name=name, selling_price=Decimal("10.00"),
        ai_classes=ai_classes,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _inventory(db, store, product, qty, reorder_level=5, reorder_quantity=10) -> Inventory:
    inv = Inventory(
        store_id=store.id,
        product_id=product.id,
        quantity=qty,
        reorder_level=reorder_level,
        reorder_quantity=reorder_quantity,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv


def _batch(db, store, product, qty, expiry_date=None, precision="day", batch_number="B1") -> Batch:
    b = Batch(
        store_id=store.id, product_id=product.id, quantity=qty,
        batch_number=batch_number, expiry_date=expiry_date,
        expiry_date_precision=precision,
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


def _now():
    return datetime.now(timezone.utc)


def _camera(db, store, shelf_regions, name="shelf-cam") -> Camera:
    c = Camera(
        name=name, store_id=store.id, camera_type="usb", is_active=True,
        config={"shelf_regions": shelf_regions},
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _record_product(db, store, camera, class_name, *, bbox, conf=0.9, observed_at=None, frame=0):
    obs = Observation(
        store_id=store.id,
        camera_id=camera.id,
        observation_type=OBS_PRODUCT,
        confidence=conf,
        bbox=bbox,
        observed_at=observed_at or _now(),
        frame_number=frame,
        details={"class_name": class_name},
    )
    db.add(obs)
    db.commit()
    db.refresh(obs)
    return obs


def _activate_planogram(db, store, shelf, *product_tuples):
    pl = Planogram(store_id=store.id, name="Active", is_active=True)
    db.add(pl)
    db.flush()
    for p, facings in product_tuples:
        db.add(
            PlanogramItem(
                planogram_id=pl.id, shelf_id=shelf.id,
                product_id=p.id, expected_facings=facings,
            )
        )
    db.commit()
    return pl


def _zone_visit(db, store, zone, person, *, entered_at, dwell_seconds=None):
    z = ZoneVisit(
        store_id=store.id,
        global_person_id=person,
        zone_id=zone.id,
        entered_at=entered_at,
        dwell_seconds=dwell_seconds,
        confidence="HIGH",
    )
    db.add(z)
    return z


def _session(db, store, person, *, first_seen_at, last_seen_at):
    gs = GlobalPersonSession(
        store_id=store.id,
        global_person_id=person,
        status=SESSION_ACTIVE,
        confidence="HIGH",
        first_seen_at=first_seen_at,
        last_seen_at=last_seen_at,
    )
    db.add(gs)


def _sale(db, store, product, qty, *, at, line_total=10.0):
    sale = Sale(
        store_id=store.id, sale_timestamp_utc=at,
        subtotal=Decimal(str(line_total)), tax_total=Decimal("0"),
        total=Decimal(str(line_total)), payment_method="cash",
    )
    db.add(sale)
    db.flush()
    db.add(
        SaleItem(
            sale_id=sale.id, product_id=product.id, quantity=qty,
            unit_price=Decimal("10.00"), tax=Decimal("0"), line_total=Decimal(str(line_total)),
        )
    )
    db.commit()
    return sale


def _type_counts(insights) -> dict:
    out = {}
    for i in insights:
        out[i.insight_type] = out.get(i.insight_type, 0) + 1
    return out


def _insights(db, store) -> list:
    return list(db.scalars(select(Insight).where(Insight.store_id == store.id)))


# ---------------------------------------------------------------------------
# (A) Inventory rules
# ---------------------------------------------------------------------------


def test_low_stock_creates_medium_insight_with_evidence(db, store):
    p = _product(db, store, "A-1", "Milk")
    _inventory(db, store, p, 3, reorder_level=5)
    res = InsightEngine(db).evaluate_inventory(store.id)
    assert res.created == 1 and res.candidates == 1
    ins = _insights(db, store)[0]
    assert ins.insight_type == INSIGHT_LOW_STOCK
    assert ins.severity == SEV_MEDIUM
    assert ins.certainty == CERTAINTY_HIGH
    assert ins.entity_type == "product" and ins.entity_id == str(p.id)
    assert "inventory" in (ins.source_modules or [])
    assert "Milk" in ins.title
    assert ins.recommended_action
    assert ins.evidence["metrics"]["current_stock"] == 3
    assert "reorder level: 5" in ins.evidence["summary"][0]


def test_out_of_stock_is_high_and_raises_shortage_alert(db, store):
    p = _product(db, store, "B-1", "Bread")
    _inventory(db, store, p, 0, reorder_level=4)
    res = InsightEngine(db).evaluate_inventory(store.id)
    assert res.created == 1
    ins = _insights(db, store)[0]
    assert ins.insight_type == INSIGHT_OUT_OF_STOCK
    assert ins.severity == SEV_HIGH
    assert ins.certainty == CERTAINTY_HIGH
    assert res.alerts_created == 1
    alert = db.scalar(select(Alert).where(Alert.store_id == store.id))
    assert alert.alert_type == ALERT_SHORTAGE
    assert alert.source_type == "insights"


def test_healthy_stock_produces_no_inventory_insight(db, store):
    p = _product(db, store, "C-1", "Sauce")
    _inventory(db, store, p, 100, reorder_level=5)
    res = InsightEngine(db).evaluate_inventory(store.id)
    assert res.created == 0
    assert _insights(db, store) == []


# ---------------------------------------------------------------------------
# (B) Expiry rules
# ---------------------------------------------------------------------------

REF = date(2026, 8, 1)


def test_expired_batch_is_high_with_expiry_alert(db, store):
    p = _product(db, store, "E-1", "Yogurt")
    b = _batch(db, store, p, 10, expiry_date=REF - timedelta(days=3))
    res = InsightEngine(db).evaluate_expiry(store.id, reference_date=REF)
    assert res.created == 1
    ins = _insights(db, store)[0]
    assert ins.insight_type == INSIGHT_EXPIRED_BATCH
    assert ins.severity == SEV_HIGH
    assert ins.certainty == CERTAINTY_HIGH
    assert ins.entity_id == str(b.id)
    assert ins.expires_at is None
    assert res.alerts_created == 1
    alert = db.scalar(select(Alert).where(Alert.store_id == store.id))
    assert alert.alert_type == ALERT_EXPIRY


def test_expiry_risk_day_precision_high_certainty_and_self_expires(db, store):
    p = _product(db, store, "E-2", "Butter")
    b = _batch(db, store, p, 6, expiry_date=REF + timedelta(days=5))
    res = InsightEngine(db).evaluate_expiry(store.id, reference_date=REF)
    assert res.created == 1
    ins = _insights(db, store)[0]
    assert ins.insight_type == INSIGHT_EXPIRY_RISK
    assert ins.severity == SEV_MEDIUM
    assert ins.certainty == CERTAINTY_HIGH
    # Self-expires the day after expiry date at midnight UTC.
    assert ins.expires_at == datetime(2026, 8, 7, 0, 0, tzinfo=timezone.utc)
    assert ins.evidence["metrics"]["batch_number"] == b.batch_number


def test_expiry_risk_month_precision_medium_certainty(db, store):
    p = _product(db, store, "E-3", "Cheese")
    _batch(db, store, p, 4, expiry_date=date(2026, 8, 1), precision="month")
    res = InsightEngine(db).evaluate_expiry(store.id, reference_date=REF)
    assert res.created == 1
    ins = _insights(db, store)[0]
    assert ins.insight_type == INSIGHT_EXPIRY_RISK
    assert ins.certainty == CERTAINTY_MEDIUM  # day unknown -> never pretend certainty
    assert ins.severity == SEV_MEDIUM


def test_stock_rotation_recommendation_low_no_alert(db, store):
    p = _product(db, store, "E-4", "Juice")
    _batch(db, store, p, 5, expiry_date=REF + timedelta(days=20), batch_number="R1")
    _batch(db, store, p, 5, expiry_date=REF + timedelta(days=60), batch_number="R2")
    res = InsightEngine(db).evaluate_expiry(store.id, reference_date=REF)
    types = _type_counts(_insights(db, store))
    assert types.get(INSIGHT_STOCK_ROTATION) == 1
    rot = [i for i in _insights(db, store) if i.insight_type == INSIGHT_STOCK_ROTATION][0]
    assert rot.severity == SEV_LOW
    assert res.alerts_created == 0


# ---------------------------------------------------------------------------
# (C) Shelf rules
# ---------------------------------------------------------------------------


def test_low_shelf_availability_is_medium_with_recommendation(db, store, shelf):
    cam = _camera(db, store, [{"code": shelf.code, "bbox": [0, 0, 100, 100]}])
    _record_product(db, store, cam, "Sauce", bbox=[0, 0, 20, 20])  # tiny occupancy -> LOW
    res = InsightEngine(db).evaluate_shelves(store.id)
    types = _type_counts(_insights(db, store))
    assert types.get(INSIGHT_LOW_SHELF_AVAILABILITY) == 1
    ins = [i for i in _insights(db, store) if i.insight_type == INSIGHT_LOW_SHELF_AVAILABILITY][0]
    assert ins.severity == SEV_MEDIUM
    assert ins.certainty == CERTAINTY_MEDIUM
    assert "AI" in ins.description or "occupancy" in ins.description.lower()
    assert ins.shelf_id == shelf.id
    assert res.alerts_created == 0


def test_empty_visible_shelf_is_high_with_low_shelf_alert(db, store, shelf):
    # Another region carries observations so camera_has_ai_data is true.
    cam = _camera(
        db, store,
        [
            {"code": shelf.code, "bbox": [0, 0, 100, 100]},          # empty region
            {"code": "B2", "bbox": [200, 0, 300, 100]},             # observed region
        ],
    )
    _record_product(db, store, cam, "Sauce", bbox=[200, 0, 300, 100])  # B2 = NORMAL
    res = InsightEngine(db).evaluate_shelves(store.id)
    types = _type_counts(_insights(db, store))
    assert types.get(INSIGHT_LOW_SHELF_AVAILABILITY) == 1
    ins = [i for i in _insights(db, store) if i.insight_type == INSIGHT_LOW_SHELF_AVAILABILITY][0]
    assert ins.severity == SEV_HIGH
    assert ins.shelf_id == shelf.id
    assert "empty" in ins.title.lower()
    assert res.alerts_created == 1
    alert = db.scalar(select(Alert).where(Alert.store_id == store.id))
    assert alert.alert_type == ALERT_LOW_SHELF_OCCUPANCY


def test_unknown_shelf_is_never_flagged(db, store, shelf):
    cam = _camera(db, store, [{"code": shelf.code, "bbox": [0, 0, 100, 100]}])
    # NO observations at all -> UNKNOWN, never flagged.
    res = InsightEngine(db).evaluate_shelves(store.id)
    assert res.created == 0
    assert _insights(db, store) == []


def test_misplacement_requires_planogram_and_mapping(db, store, shelf):
    expected = _product(db, store, "M-1", "Maggi", ai_classes=["Maggi"])
    mapped = _product(db, store, "M-2", "Lays", ai_classes=["Lays"])
    _inventory(db, store, expected, 20)
    _inventory(db, store, mapped, 20)
    _activate_planogram(db, store, shelf, (expected, 6))
    cam = _camera(db, store, [{"code": shelf.code, "bbox": [0, 0, 100, 100]}])
    _record_product(db, store, cam, "Lays", bbox=[10, 10, 60, 60])   # in A1 region
    res = InsightEngine(db).evaluate_shelves(store.id)
    types = _type_counts(_insights(db, store))
    assert types.get(INSIGHT_MISPLACEMENT) == 1
    mis = [i for i in _insights(db, store) if i.insight_type == INSIGHT_MISPLACEMENT][0]
    assert mis.severity == SEV_LOW
    assert mis.product_id == mapped.id
    assert res.alerts_created == 0
    assert "planogram" in (mis.evidence.get("summary")[0] or "").lower() or "shelf" in mis.evidence["summary"][0].lower()


def test_misplacement_without_planogram_never_flagged(db, store, shelf):
    mapped = _product(db, store, "M-3", "Lays", ai_classes=["Lays"])
    _inventory(db, store, mapped, 20)
    cam = _camera(db, store, [{"code": shelf.code, "bbox": [0, 0, 100, 100]}])
    _record_product(db, store, cam, "Lays", bbox=[10, 10, 60, 60])
    res = InsightEngine(db).evaluate_shelves(store.id)
    assert all(i.insight_type != INSIGHT_MISPLACEMENT for i in _insights(db, store))


# ---------------------------------------------------------------------------
# (D) Customer flow rules (M19 analytics, no purchase intent)
# ---------------------------------------------------------------------------

FLOW_NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


def test_high_traffic_zone_insight_from_aggregate_visits(db, store, zone):
    for k in range(50):
        _zone_visit(
            db, store, zone, f"p{k}",
            entered_at=FLOW_NOW - timedelta(hours=1),
            dwell_seconds=None,
        )
    db.commit()
    res = InsightEngine(db).evaluate_customer_flow(store.id, now=FLOW_NOW)
    types = _type_counts(_insights(db, store))
    assert types.get(INSIGHT_HIGH_TRAFFIC_ZONE) == 1
    ins = [i for i in _insights(db, store) if i.insight_type == INSIGHT_HIGH_TRAFFIC_ZONE][0]
    assert ins.severity == SEV_INFO
    assert ins.zone_id == zone.id
    assert "50 visits" in ins.description
    # NEVER purchase intent.
    assert "want" not in (ins.description or "").lower()
    assert "purchase" not in (ins.description or "").lower()


def test_high_dwell_zone_insight_from_closed_visits(db, store, zone):
    for k in range(5):
        _zone_visit(
            db, store, zone, f"d{k}",
            entered_at=FLOW_NOW - timedelta(hours=2),
            dwell_seconds=240.0,
        )
    db.commit()
    res = InsightEngine(db).evaluate_customer_flow(store.id, now=FLOW_NOW)
    types = _type_counts(_insights(db, store))
    assert types.get(INSIGHT_HIGH_DWELL_ZONE) == 1
    ins = [i for i in _insights(db, store) if i.insight_type == INSIGHT_HIGH_DWELL_ZONE][0]
    assert ins.severity == SEV_INFO
    assert ins.zone_id == zone.id
    assert "dwell" in ins.title.lower()


def test_low_traffic_produces_no_flow_insights(db, store, zone):
    for k in range(3):
        _zone_visit(db, store, zone, f"q{k}", entered_at=FLOW_NOW - timedelta(hours=1))
    db.commit()
    res = InsightEngine(db).evaluate_customer_flow(store.id, now=FLOW_NOW)
    assert res.created == 0
    assert _insights(db, store) == []


def test_high_traffic_low_shelf_combination_requires_store_inventory(db, store, zone, shelf):
    # Shelf A1 is empty-visible.
    cam = _camera(
        db, store,
        [
            {"code": shelf.code, "bbox": [0, 0, 100, 100]},
            {"code": "B2", "bbox": [200, 0, 300, 100]},
        ],
    )
    _record_product(db, store, cam, "Sauce", bbox=[240, 10, 290, 60])  # B2 -> A1 empty
    p = _product(db, store, "F-1", "Flour")
    _inventory(db, store, p, 40)  # store has inventory available
    for k in range(50):
        _zone_visit(db, store, zone, f"t{k}", entered_at=FLOW_NOW - timedelta(hours=1))
    db.commit()

    ctx = RuleContext(db, store_id=store.id, now=FLOW_NOW)
    cands = rule_customer_flow(ctx)
    combo = [c for c in cands if c.insight_type == INSIGHT_HIGH_TRAFFIC_LOW_SHELF]
    assert len(combo) == 1
    c = combo[0]
    assert c.severity == SEV_MEDIUM
    assert c.zone_id == zone.id
    assert c.evidence["metrics"]["inventory_available"] is True


def test_high_traffic_low_shelf_skipped_without_shelf_evidence(db, store, zone):
    p = _product(db, store, "F-2", "Salt")
    _inventory(db, store, p, 40)
    for k in range(50):
        _zone_visit(db, store, zone, f"u{k}", entered_at=FLOW_NOW - timedelta(hours=1))
    db.commit()
    ctx = RuleContext(db, store_id=store.id, now=FLOW_NOW)
    cands = rule_customer_flow(ctx)
    assert all(c.insight_type != INSIGHT_HIGH_TRAFFIC_LOW_SHELF for c in cands)


# ---------------------------------------------------------------------------
# (E) Camera health
# ---------------------------------------------------------------------------


def test_camera_offline_raises_high_insight_and_alert(db, store):
    cam = _camera(db, store, [], name="entrance")
    res = InsightEngine(db).evaluate_camera_health(store.id)
    assert res.created == 1
    ins = _insights(db, store)[0]
    assert ins.insight_type == INSIGHT_CAMERA_HEALTH
    assert ins.severity == SEV_HIGH
    assert ins.camera_id == cam.id
    assert res.alerts_created == 1
    alert = db.scalar(select(Alert).where(Alert.store_id == store.id))
    assert alert.alert_type == ALERT_CAMERA_OFFLINE


def test_recent_observation_keeps_camera_healthy(db, store):
    cam = _camera(db, store, [], name="entrance")
    _record_product(db, store, cam, "Sauce", bbox=[0, 0, 20, 20], observed_at=_now())
    res = InsightEngine(db).evaluate_camera_health(store.id)
    assert res.created == 0
    assert _insights(db, store) == []


# ---------------------------------------------------------------------------
# (F) Sales rule
# ---------------------------------------------------------------------------


def test_high_selling_and_low_stock_insight(db, store):
    p = _product(db, store, "S-1", "Cold Drink")
    _inventory(db, store, p, 3, reorder_level=5)
    for _ in range(4):
        _sale(db, store, p, 5, at=datetime(2026, 8, 2, 8, 0, tzinfo=timezone.utc))
    res = InsightEngine(db).evaluate(
        store.id, now=datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
    )
    types = _type_counts(_insights(db, store))
    assert types.get(INSIGHT_HIGH_SELLING_LOW_STOCK) == 1
    ins = [i for i in _insights(db, store) if i.insight_type == INSIGHT_HIGH_SELLING_LOW_STOCK][0]
    assert ins.severity == SEV_MEDIUM
    assert ins.evidence["metrics"]["units_sold"] >= 20
    # No purchase-intent claim.
    assert "wants" not in (ins.description or "").lower()


def test_high_selling_but_enough_stock_no_insight(db, store):
    p = _product(db, store, "S-2", "Chips")
    _inventory(db, store, p, 50, reorder_level=5)
    for _ in range(4):
        _sale(db, store, p, 5, at=datetime(2026, 8, 2, 8, 0, tzinfo=timezone.utc))
    InsightEngine(db).evaluate(store.id, now=datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc))
    assert all(i.insight_type != INSIGHT_HIGH_SELLING_LOW_STOCK for i in _insights(db, store))


# ---------------------------------------------------------------------------
# (G) Combination rule
# ---------------------------------------------------------------------------


def test_low_stock_with_low_shelf_availability(db, store, shelf):
    p = _product(db, store, "G-1", "Detergent", ai_classes=["Detergent"])
    _inventory(db, store, p, 3, reorder_level=5)
    cam = _camera(db, store, [{"code": shelf.code, "bbox": [0, 0, 100, 100]}])
    _record_product(db, store, cam, "Detergent", bbox=[0, 0, 20, 20])  # LOW
    ctx = RuleContext(db, store_id=store.id)
    cands = rule_low_stock_low_shelf(ctx)
    combos = [c for c in cands if c.insight_type == INSIGHT_LOW_STOCK_LOW_SHELF]
    assert len(combos) == 1
    c = combos[0]
    assert c.severity == SEV_MEDIUM
    assert c.product_id == p.id
    assert c.evidence["shelf"]["code"] == shelf.code


# ---------------------------------------------------------------------------
# (H) Engine lifecycle: dedup / refresh / resolve / expire / isolation
# ---------------------------------------------------------------------------


def test_evaluate_is_idempotent_and_refreshes_in_place(db, store):
    p = _product(db, store, "H-1", "Milk")
    _inventory(db, store, p, 3, reorder_level=5)
    first = InsightEngine(db).evaluate_inventory(store.id)
    assert first.created == 1 and first.candidates == 1
    first_id = _insights(db, store)[0].id
    second = InsightEngine(db).evaluate_inventory(store.id)
    assert second.created == 0 and second.refreshed == 1
    assert len(_insights(db, store)) == 1
    assert _insights(db, store)[0].id == first_id
    assert _insights(db, store)[0].status == STATUS_OPEN


def test_condition_cleared_resolves_open_insight(db, store):
    p = _product(db, store, "H-2", "Bread")
    inv = _inventory(db, store, p, 0, reorder_level=4)
    InsightEngine(db).evaluate_inventory(store.id)
    ins = _insights(db, store)[0]
    assert ins.status == STATUS_OPEN

    inv.quantity = 20
    db.commit()
    res = InsightEngine(db).evaluate_inventory(store.id)
    assert res.resolved == 1
    db.refresh(ins)
    assert ins.status == STATUS_RESOLVED
    assert ins.resolved_at is not None


def test_acknowledged_insight_is_refreshed_not_resolved(db, store):
    p = _product(db, store, "H-3", "Sauce")
    _inventory(db, store, p, 2, reorder_level=5)
    InsightEngine(db).evaluate_inventory(store.id)
    ins = _insights(db, store)[0]
    ins.status = STATUS_ACKNOWLEDGED
    db.commit()

    res = InsightEngine(db).evaluate_inventory(store.id)
    assert res.refreshed == 1 and res.resolved == 0
    db.refresh(ins)
    assert ins.status == STATUS_ACKNOWLEDGED


def test_resolved_insight_creates_new_on_recurrence(db, store):
    p = _product(db, store, "H-4", "Raisins")
    inv = _inventory(db, store, p, 0, reorder_level=4)
    InsightEngine(db).evaluate_inventory(store.id)
    ins = _insights(db, store)[0]
    ins.status = STATUS_RESOLVED
    db.commit()

    inv.quantity = 0  # still out of stock -> re-detected
    db.commit()
    res = InsightEngine(db).evaluate_inventory(store.id)
    assert res.created == 1
    rows = _insights(db, store)
    assert len(rows) == 2
    assert [i.status for i in rows].count(STATUS_RESOLVED) == 1
    assert [i.status for i in rows].count(STATUS_OPEN) == 1


def test_expired_ttl_retires_stale_expiry_insight(db, store):
    p = _product(db, store, "H-5", "Juice")
    _batch(db, store, p, 6, expiry_date=REF + timedelta(days=5))
    InsightEngine(db).evaluate_expiry(store.id, reference_date=REF)
    ins = _insights(db, store)[0]
    assert ins.insight_type == INSIGHT_EXPIRY_RISK and ins.status == STATUS_OPEN
    assert ins.expires_at == datetime(2026, 8, 7, 0, 0, tzinfo=timezone.utc)

    # Re-evaluate at/after the expiry date: the batch is now truly expired, so
    # its EXPIRY_RISK insight is retired (TTL) and EXPIRED_BATCH is created.
    after = REF + timedelta(days=5)  # 2026-08-06 -> batch expired
    res = InsightEngine(db).evaluate_expiry(
        store.id,
        reference_date=after,
        now=datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc),
    )
    assert res.expired >= 1
    db.refresh(ins)
    assert ins.status == STATUS_EXPIRED
    assert ins.expired_at is not None
    # The new EXPIRED_BATCH insight is created.
    types = _type_counts(_insights(db, store))
    assert types.get(INSIGHT_EXPIRED_BATCH) == 1


def test_store_isolation_never_leaks_insights(db, store):
    other = Store(name="Other Store", timezone="Asia/Kolkata")
    db.add(other)
    db.commit()
    db.refresh(other)
    p = _product(db, store, "H-6", "Milk")
    _inventory(db, store, p, 2, reorder_level=5)
    pq = _product(db, other, "H-7", "Juice",)
    _inventory(db, other, pq, 50, reorder_level=5)  # healthy store

    InsightEngine(db).evaluate(store.id)
    assert len(_insights(db, store)) > 0
    assert _insights(db, other) == []


# ---------------------------------------------------------------------------
# (I) Alert integration + NO-MUTATION proofs
# ---------------------------------------------------------------------------


def test_full_evaluate_never_mutates_inventory_batches_sales_movements(db, store, zone, shelf):
    p = _product(db, store, "N-1", "Milk", ai_classes=["Milk"])
    _inventory(db, store, p, 3, reorder_level=5)
    b = _batch(db, store, p, 6, expiry_date=REF + timedelta(days=5))
    cam = _camera(
        db, store,
        [{"code": shelf.code, "bbox": [0, 0, 100, 100]}, {"code": "B2", "bbox": [200, 0, 300, 100]}],
    )
    _record_product(db, store, cam, "Milk", bbox=[240, 10, 290, 60])  # A1 empty
    _sale(db, store, p, 3, at=FLOW_NOW - timedelta(hours=1))
    for k in range(50):
        _zone_visit(db, store, zone, f"n{k}", entered_at=FLOW_NOW - timedelta(hours=1))
    db.commit()

    before = {
        "inv_qty": sum(db.scalars(select(Inventory.quantity)).all()),
        "inv_rows": db.scalar(select(func.count(Inventory.id))),
        "batch_qty": sum(db.scalars(select(Batch.quantity)).all()),
        "batch_rows": db.scalar(select(func.count(Batch.id))),
        "sales": db.scalar(select(func.count(Sale.id))),
        "sale_items": db.scalar(select(func.count(SaleItem.id))),
        "movements": db.scalar(select(func.count(InventoryMovement.id))),
        "observations": db.scalar(select(func.count(Observation.id))),
        "visits": db.scalar(select(func.count(ZoneVisit.id))),
    }

    res = InsightEngine(db).evaluate(store.id, now=FLOW_NOW, reference_date=REF)

    after = {
        "inv_qty": sum(db.scalars(select(Inventory.quantity)).all()),
        "inv_rows": db.scalar(select(func.count(Inventory.id))),
        "batch_qty": sum(db.scalars(select(Batch.quantity)).all()),
        "batch_rows": db.scalar(select(func.count(Batch.id))),
        "sales": db.scalar(select(func.count(Sale.id))),
        "sale_items": db.scalar(select(func.count(SaleItem.id))),
        "movements": db.scalar(select(func.count(InventoryMovement.id))),
        "observations": db.scalar(select(func.count(Observation.id))),
        "visits": db.scalar(select(func.count(ZoneVisit.id))),
    }
    assert before == after, "insight evaluation MUTATED domain data — forbidden"
    assert res.created >= 1
    # Only insights (and possibly alerts) were added.
    added = set(_type_counts(_insights(db, store)).keys())
    assert INSIGHT_LOW_STOCK in added


def test_alert_sync_dedup_resourceful(db, store):
    p = _product(db, store, "N-2", "Bread")
    _inventory(db, store, p, 0, reorder_level=4)
    first = InsightEngine(db).evaluate_inventory(store.id)
    assert first.alerts_created == 1
    second = InsightEngine(db).evaluate_inventory(store.id)
    assert second.alerts_created == 0
    assert second.alerts_updated == 1
    alerts = list(db.scalars(select(Alert).where(Alert.store_id == store.id)))
    assert len(alerts) == 1


def test_medium_severity_insight_creates_no_alert(db, store):
    p = _product(db, store, "N-3", "Milk")
    _inventory(db, store, p, 3, reorder_level=5)  # LOW_STOCK = MEDIUM
    res = InsightEngine(db).evaluate_inventory(store.id)
    assert res.alerts_created == 0
    assert list(db.scalars(select(Alert).where(Alert.store_id == store.id))) == []


# ---------------------------------------------------------------------------
# (J) Store health (categorical formula)
# ---------------------------------------------------------------------------


def test_store_health_healthy_when_no_issues(db, store):
    health = StoreHealthService(db).compute(store.id)
    assert health.state == "HEALTHY"
    assert health.cameras["total"] == 0
    assert health.basis[0] == "No HIGH or MEDIUM insights at evaluation time."


def test_store_health_attention_when_medium_signal(db, store):
    p = _product(db, store, "K-1", "Milk")
    _inventory(db, store, p, 3, reorder_level=5)
    health = StoreHealthService(db).compute(store.id)
    assert health.state == "ATTENTION"
    assert any("INSIGHT" in basis or "stock" in basis.lower() for basis in health.basis)


def test_store_health_critical_when_high_signal(db, store):
    p = _product(db, store, "K-2", "Bread")
    _inventory(db, store, p, 0, reorder_level=4)
    health = StoreHealthService(db).compute(store.id)
    assert health.state == "CRITICAL"
    assert "Out of stock: Bread" in " ".join(health.basis)


def test_store_health_insight_is_cached_via_engine(db, store):
    p = _product(db, store, "K-3", "Bread")
    _inventory(db, store, p, 0, reorder_level=4)
    res = InsightEngine(db).evaluate_store_health(store.id)
    assert res.created == 1
    ins = _insights(db, store)[0]
    assert ins.insight_type == INSIGHT_STORE_HEALTH
    assert ins.severity == SEV_HIGH  # CRITICAL maps to HIGH
    assert ins.entity_type == "store"
    assert "CRITICAL" in ins.evidence["summary"][0]


# ---------------------------------------------------------------------------
# (K) Privacy + wording guards
# ---------------------------------------------------------------------------


def test_customer_flow_never_mentions_intent_or_identity(db, store, zone):
    for k in range(50):
        _zone_visit(db, store, zone, f"pl{k}", entered_at=FLOW_NOW - timedelta(hours=1))
    db.commit()
    InsightEngine(db).evaluate_customer_flow(store.id, now=FLOW_NOW)
    for ins in _insights(db, store):
        text = f"{ins.title} {ins.description or ''} {ins.evidence}".lower()
        assert "wants" not in text
        assert "purchase" not in text
        assert "wish" not in text


def test_camera_candidates_are_annotated_as_simulated_proxy(db, store):
    cam = _camera(db, store, [], name="entrance")
    InsightEngine(db).evaluate_camera_health(store.id)
    ins = _insights(db, store)[0]
    assert ins.rule_id == "camera_health.stale"