"""Milestone 16 tests: Alerts + Actionable Intelligence.

Integration tests against the isolated storeye_test database. Verify the alert
layer:

    * creates, deduplicates, filters and pages alerts deterministically;
    * generates the 7 alert types by REUSING existing M15 intelligence results
      (product/shelf/expiry/reconciliation/camera staleness) — never re-running
      camera inference and never touching the network;
    * honours the confidence threshold, skips unmapped products, and never
      guesses alerts for products absent from planogram expectations or for
      UNKNOWN shelves (no evidence);
    * enforces the domain lifecycle OPEN -> ACKNOWLEDGED -> RESOLVED /
      OPEN -> DISMISSED and treats terminal states as terminal;
    * NEVER mutates inventory / inventory_movements / batches / bills / sales;
    * exposes the /api/alerts CRUD + lifecycle + evaluate endpoints over HTTP.

Alerts are informational/actionable notifications — inventory adjustment stays
an explicit, human-reviewed operation.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models import (
    ALERT_CAMERA_OFFLINE,
    ALERT_EXPIRY,
    ALERT_LOW_SHELF_OCCUPANCY,
    ALERT_MISPLACEMENT,
    ALERT_REVIEW_REQUIRED,
    ALERT_SHORTAGE,
    ALERT_SURPLUS,
    Alert,
    BATCH_PRECISION_DAY,
    BATCH_PRECISION_MONTH,
    Batch,
    Bill,
    Camera,
    Inventory,
    InventoryMovement,
    Planogram,
    PlanogramItem,
    Product,
    REC_REVIEW,
    ReconciliationResult,
    SEV_CRITICAL,
    SEV_HIGH,
    SEV_LOW,
    SEV_MEDIUM,
    STATUS_ACKNOWLEDGED,
    STATUS_DISMISSED,
    STATUS_OPEN,
    STATUS_RESOLVED,
    Sale,
    Shelf,
    Store,
    Zone,
)
from app.services.alerts import (
    AlertRuleEngine,
    AlertService,
    InvalidStatusTransitionError,
    ValidationError,
)
from app.services.observations import ObservationService

pytestmark = pytest.mark.pg

TEST_DB_URL = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg2://storeye@localhost:5433/storeye_test")


def _now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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
def session_factory(engine):
    with engine.begin() as conn:
        Base.metadata.drop_all(conn)
        Base.metadata.create_all(conn)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory


@pytest.fixture()
def store(db) -> Store:
    s = Store(name="Alert Store", timezone="Asia/Kolkata")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@pytest.fixture()
def zone(db, store) -> Zone:
    z = Zone(store_id=store.id, name="Snacks")
    db.add(z)
    db.commit()
    db.refresh(z)
    return z


@pytest.fixture()
def shelf(db, store, zone) -> Shelf:
    s = Shelf(store_id=store.id, zone_id=zone.id, code="A1")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@pytest.fixture()
def product(db, store) -> Product:
    p = Product(store_id=store.id, sku="ALR-LAYS", name="Lays", selling_price=10, ai_classes=["Lays"])
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture()
def mapped_product(db, store) -> Product:
    p = Product(store_id=store.id, sku="ALR-MAGGI", name="Maggi", selling_price=14, ai_classes=["Maggi"])
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _camera(db, store, name, config, active=True) -> Camera:
    c = Camera(name=name, store_id=store.id, config=config, is_active=active)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@pytest.fixture()
def camera(db, store):
    return _camera(
        db, store, "alerts-shelf-cam",
        config={
            "shelf_regions": [
                {"code": "A1", "label": "Aisle A top", "bbox": [0, 0, 100, 100]},
                {"code": "B2", "bbox": [200, 0, 300, 100]},
            ]
        },
    )


@pytest.fixture()
def plain_camera(db, store):
    return _camera(db, store, "alerts-plain-cam", config=None)


def _record_product(db, store, camera, class_name, *, bbox, conf=0.9, frame=0, observed_at=None, product_id=None):
    return ObservationService(db).record_product_observation(
        store_id=store.id,
        camera_id=camera.id,
        product_id=product_id,
        confidence=conf,
        bbox=bbox,
        frame_number=frame,
        observed_at=observed_at or _now(),
        details={"class_name": class_name},
    )


def _set_inventory(db, store, product, qty):
    inv = db.scalar(select(Inventory).where(Inventory.store_id == store.id, Inventory.product_id == product.id))
    if inv is None:
        inv = Inventory(store_id=store.id, product_id=product.id, quantity=qty)
    else:
        inv.quantity = qty
    db.add(inv)
    db.commit()
    return inv


def _activate_planogram(db, store, shelf, *product_tuples):
    pl = Planogram(store_id=store.id, name="Active", is_active=True)
    db.add(pl)
    db.flush()
    for p, facings in product_tuples:
        db.add(PlanogramItem(planogram_id=pl.id, shelf_id=shelf.id, product_id=p.id, expected_facings=facings))
    db.commit()
    return pl


def _alerts_of(db, alert_type, store_id):
    return list(
        db.scalars(
            select(Alert).where(
                Alert.alert_type == alert_type,
                Alert.store_id == store_id,
            )
        )
    )


def _count(db, model):
    return db.query(model).count()


# ---------------------------------------------------------------------------
# Create / deduplicate
# ---------------------------------------------------------------------------

def test_create_alert_and_fk_context(db, store, product, camera, shelf):
    a, created = AlertService(db).create_alert(
        store_id=store.id, alert_type=ALERT_SHORTAGE, severity=SEV_MEDIUM,
        title="Stock low", message="Check it", camera_id=camera.id,
        product_id=product.id, shelf_id=shelf.id, confidence=0.9,
        source_type="manual", details={"note": "manual"},
    )
    assert created is True
    assert a.status == STATUS_OPEN
    assert a.store_id == store.id
    assert a.camera_id == camera.id and a.product_id == product.id and a.shelf_id == shelf.id
    assert a.first_detected_at == a.last_detected_at
    assert a.details == {"note": "manual"}
    assert _count(db, Alert) == 1


def test_create_alert_validation_rejects_bad_type_and_severity(db, store):
    svc = AlertService(db)
    with pytest.raises(ValidationError):
        svc.create_alert(store_id=store.id, alert_type="NOPE", severity=SEV_LOW, title="x")
    with pytest.raises(ValidationError):
        svc.create_alert(store_id=store.id, alert_type=ALERT_SHORTAGE, severity="PURPLE", title="x")
    with pytest.raises(ValidationError):
        svc.create_alert(store_id=store.id, alert_type=ALERT_SHORTAGE, severity=SEV_LOW, title="  ")


def test_dedup_updates_existing_open_alert(db, store, product, camera):
    svc = AlertService(db)
    a1, created1 = svc.create_alert(
        store_id=store.id, alert_type=ALERT_SHORTAGE, severity=SEV_MEDIUM,
        title="T1", product_id=product.id, camera_id=camera.id,
        confidence=0.7, details={"d": 1},
    )
    a2, created2 = svc.create_alert(
        store_id=store.id, alert_type=ALERT_SHORTAGE, severity=SEV_HIGH,
        title="T2", product_id=product.id, camera_id=camera.id,
        confidence=0.95, details={"newer": True},
    )
    assert created1 is True and created2 is False
    assert a2.id == a1.id
    a2 = db.get(Alert, a1.id)
    assert a2.status == STATUS_OPEN
    assert a2.title == "T2" and a2.severity == SEV_HIGH and a2.confidence == 0.95
    assert a2.details["d"] == 1 and a2.details["newer"] is True  # merged evidence
    assert _count(db, Alert) == 1


def test_different_contexts_are_separate_alerts(db, store, product, camera):
    svc = AlertService(db)
    svc.create_alert(store_id=store.id, alert_type=ALERT_SHORTAGE, severity=SEV_LOW, title="P", product_id=product.id, camera_id=camera.id)
    svc.create_alert(store_id=store.id, alert_type=ALERT_SURPLUS, severity=SEV_LOW, title="P", product_id=product.id, camera_id=camera.id)
    assert _count(db, Alert) == 2


def test_query_filters_and_pagination(db, store, camera):
    svc = AlertService(db)
    products = []
    for i in range(5):
        p = Product(store_id=store.id, sku=f"ALR-Q{i}", name=f"Prod {i}", selling_price=10)
        db.add(p)
        db.flush()
        products.append(p)
    for p in products:
        svc.create_alert(
            store_id=store.id, alert_type=ALERT_SHORTAGE, severity=SEV_MEDIUM,
            title=f"N{p.sku}", product_id=p.id, camera_id=camera.id,
        )
    svc.create_alert(store_id=store.id, alert_type=ALERT_EXPIRY, severity=SEV_HIGH, title="Exp", product_id=products[0].id)
    svc.create_alert(store_id=store.id, alert_type=ALERT_SHORTAGE, severity=SEV_HIGH, title="H", product_id=products[1].id)

    items, total = svc.query_alerts(store_id=store.id, limit=100)
    assert total == 7 and len(items) == 7

    items, total = svc.query_alerts(store_id=store.id, alert_type=ALERT_SHORTAGE, limit=100)
    assert total == 6

    items, total = svc.query_alerts(store_id=store.id, severity=SEV_HIGH, limit=100)
    assert total == 2

    items, total = svc.query_alerts(store_id=store.id, status=STATUS_OPEN, limit=100)
    assert total == 7

    items, total = svc.query_alerts(store_id=store.id, limit=2, offset=2)
    assert total == 7 and len(items) == 2

    created_from = _now() - timedelta(seconds=1)
    created_to = _now() + timedelta(seconds=1)
    items, total = svc.query_alerts(store_id=store.id, created_from=created_from, created_to=created_to, limit=100)
    assert total == 7

    with pytest.raises(ValidationError):
        svc.query_alerts(store_id=store.id, alert_type="NOPE")


# ---------------------------------------------------------------------------
# Rule engine: SHORTAGE / SURPLUS
# ---------------------------------------------------------------------------

def test_shortage_alert_generation_and_severity(db, store, plain_camera, product):
    _set_inventory(db, store, product, 4)
    _record_product(db, store, plain_camera, "Lays", bbox=[0, 0, 20, 20])  # visible 1/4 -> diff -3, frac 0.75
    res = AlertRuleEngine(db).evaluate(store_id=store.id)
    assert res.generated == 1 and res.updated == 0 and res.skipped == 0
    alerts = _alerts_of(db, ALERT_SHORTAGE, store.id)
    assert len(alerts) == 1
    a = alerts[0]
    assert a.severity == SEV_CRITICAL  # fraction 0.75 >= 0.5
    assert a.product_id == product.id and a.camera_id == plain_camera.id
    assert a.status == STATUS_OPEN
    assert a.details["source"] == "product_intelligence"
    assert a.details["database_quantity"] == 4
    assert a.details["ai_observed_quantity"] == 1
    assert a.details["difference"] == -3
    assert a.details["counting_rule"] == "max_simultaneous_per_frame"
    assert "review before" in (a.message or "").lower()


def test_shortage_severity_medium(db, store, plain_camera, product):
    # fraction < 0.2 -> MEDIUM (diff -1 of db 10).
    _set_inventory(db, store, product, 10)
    for k in range(9):
        _record_product(db, store, plain_camera, "Lays", bbox=[k * 30, 0, k * 30 + 20, 20], frame=0)
    res = AlertRuleEngine(db).evaluate(store_id=store.id)
    a = _alerts_of(db, ALERT_SHORTAGE, store.id)[0]
    assert res.generated == 1
    assert a.severity == SEV_MEDIUM  # (10-9)/10 = 0.1

    # Re-run to verify dedup on second evaluation.
    res2 = AlertRuleEngine(db).evaluate(store_id=store.id)
    assert res2.generated == 0 and res2.updated == 1
    assert _count(db, Alert) == 1


def test_confidence_threshold_skips_weak_evidence(db, store, plain_camera, product):
    _set_inventory(db, store, product, 9)
    _record_product(db, store, plain_camera, "Lays", bbox=[0, 0, 20, 20], conf=0.5)
    res = AlertRuleEngine(db).evaluate(store_id=store.id, alert_confidence_threshold=0.9)
    assert res.generated == 0
    assert _alerts_of(db, ALERT_SHORTAGE, store.id) == []
    # But with a permissive threshold the same weak evidence does generate it.
    res2 = AlertRuleEngine(db).evaluate(store_id=store.id, alert_confidence_threshold=0.5)
    assert res2.generated == 1
    assert len(_alerts_of(db, ALERT_SHORTAGE, store.id)) == 1


def test_surplus_alert_generation_and_severities(db, store, plain_camera, product):
    _set_inventory(db, store, product, 2)
    for k in range(8):
        _record_product(db, store, plain_camera, "Lays", bbox=[k * 30, 0, k * 30 + 20, 20], frame=0)
    res = AlertRuleEngine(db).evaluate(store_id=store.id)
    a = _alerts_of(db, ALERT_SURPLUS, store.id)[0]
    assert a.severity == SEV_HIGH  # diff 6 / db 2 -> fraction 3.0 >= 0.5
    assert a.details["ai_observed_quantity"] == 8 and a.details["database_quantity"] == 2


def test_unmapped_class_never_generates_shortage_or_surplus(db, store, plain_camera):
    _record_product(db, store, plain_camera, "CocaCola", bbox=[0, 0, 20, 20], conf=0.9)
    res = AlertRuleEngine(db).evaluate(store_id=store.id)
    assert res.generated == 0
    assert _alerts_of(db, ALERT_SHORTAGE, store.id) == []
    assert _alerts_of(db, ALERT_SURPLUS, store.id) == []


# ---------------------------------------------------------------------------
# Rule engine: MISPLACEMENT (planogram-based, mapped products only)
# ---------------------------------------------------------------------------

def test_misplacement_alert_only_with_expectations(db, store, camera, shelf, product, mapped_product):
    # No planogram -> no misplacement guess.
    AlertRuleEngine(db).evaluate(store_id=store.id)
    assert _alerts_of(db, ALERT_MISPLACEMENT, store.id) == []

    # Activate a planogram expecting ONLY Maggi on A1.
    _activate_planogram(db, store, shelf, (mapped_product, 6))
    _record_product(db, store, camera, "Lays", bbox=[60, 0, 80, 20], conf=0.9)  # inside region A1
    res = AlertRuleEngine(db).evaluate(store_id=store.id)

    mis = _alerts_of(db, ALERT_MISPLACEMENT, store.id)
    assert len(mis) == 1
    m = mis[0]
    assert m.severity == SEV_LOW
    assert m.product_id == product.id and m.shelf_id == shelf.id
    assert m.details["expected_product"] == "Maggi"
    assert m.details["detected_product"] == "Lays"
    assert m.details["shelf_code"] == "A1"


# ---------------------------------------------------------------------------
# Rule engine: LOW_SHELF_OCCUPANCY (low only; UNKNOWN never alerts)
# ---------------------------------------------------------------------------

def test_low_shelf_occupancy_alert(db, store, camera, shelf):
    _record_product(db, store, camera, "Lays", bbox=[0, 0, 20, 20], conf=0.9)  # 400/10000 -> 4% occupancy
    res = AlertRuleEngine(db).evaluate(store_id=store.id)
    lows = _alerts_of(db, ALERT_LOW_SHELF_OCCUPANCY, store.id)
    assert res.generated >= 1
    assert len(lows) == 1
    assert lows[0].shelf_id == shelf.id
    assert lows[0].severity == SEV_MEDIUM  # pct < 15
    assert lows[0].details["occupied_pct"] == 4.0
    assert lows[0].details["detection_status"] == "LOW_VISIBLE"


def test_unknown_shelf_is_never_an_alert(db, store):
    # camera configured with regions but NO observations -> UNKNOWN, no low alert.
    _camera(db, store, "idle-region-cam", config={"shelf_regions": [{"code": "A1", "bbox": [0, 0, 100, 100]}]})
    res = AlertRuleEngine(db).evaluate(store_id=store.id)
    assert _alerts_of(db, ALERT_LOW_SHELF_OCCUPANCY, store.id) == []
    # CAMERA_OFFLINE is expected for the idle camera, but that is a separate rule.
    assert res.generated == 1
    assert len(_alerts_of(db, ALERT_CAMERA_OFFLINE, store.id)) == 1


# ---------------------------------------------------------------------------
# Rule engine: EXPIRY
# ---------------------------------------------------------------------------

def test_expiry_alert_expiring_soon(db, store):
    p = Product(store_id=store.id, sku="ALR-EX", name="ExProduct", selling_price=5)
    db.add(p)
    db.flush()
    b = Batch(
        store_id=store.id, product_id=p.id,
        batch_number="B1", expiry_date=date(2026, 9, 9),
        expiry_date_precision=BATCH_PRECISION_DAY, quantity=4,
    )
    db.add(b)
    db.commit()

    res = AlertRuleEngine(db).evaluate(
        store_id=store.id, reference_date=date(2026, 9, 7), expiry_warning_days=7,
    )
    ex = _alerts_of(db, ALERT_EXPIRY, store.id)
    assert len(ex) == 1
    assert ex[0].severity == SEV_MEDIUM  # EXPIRING_SOON
    assert ex[0].product_id == p.id
    assert ex[0].details["status"] == "EXPIRING_SOON"
    assert ex[0].details["days_until_expiry"] == 2
    assert ex[0].details["batch_id"] == str(b.id)


def test_expiry_alert_expired_is_high(db, store):
    p = Product(store_id=store.id, sku="ALR-EX2", name="StaleProduct", selling_price=5)
    db.add(p)
    db.flush()
    b = Batch(
        store_id=store.id, product_id=p.id, batch_number="B2",
        expiry_date=date(2026, 9, 1), expiry_date_precision=BATCH_PRECISION_DAY, quantity=3,
    )
    db.add(b)
    db.commit()
    res = AlertRuleEngine(db).evaluate(store_id=store.id, reference_date=date(2026, 9, 7))
    ex = _alerts_of(db, ALERT_EXPIRY, store.id)
    assert len(ex) == 1 and ex[0].severity == SEV_HIGH
    assert ex[0].details["status"] == "EXPIRED"


def test_expiry_month_precision_alert(db, store):
    p = Product(store_id=store.id, sku="ALR-EX3", name="MonthProduct", selling_price=5)
    db.add(p)
    db.flush()
    b = Batch(
        store_id=store.id, product_id=p.id, batch_number="B3",
        expiry_date=date(2026, 9, 1), expiry_date_precision=BATCH_PRECISION_MONTH, quantity=3,
    )
    db.add(b)
    db.commit()
    res = AlertRuleEngine(db).evaluate(store_id=store.id, reference_date=date(2026, 8, 20), expiry_warning_days=15)
    ex = _alerts_of(db, ALERT_EXPIRY, store.id)
    assert len(ex) == 1 and ex[0].severity == SEV_MEDIUM
    assert ex[0].details["status"] == "EXPIRY_MONTH"


# ---------------------------------------------------------------------------
# Rule engine: REVIEW_REQUIRED from reconciliation layer
# ---------------------------------------------------------------------------

def test_review_required_alert_from_reconciliation(db, store, product, camera):
    now = _now()
    db.add(
        ReconciliationResult(
            store_id=store.id, product_id=product.id, camera_id=camera.id,
            observation_window_start=now - timedelta(hours=2),
            observation_window_end=now,
            database_quantity=4, ai_observed_quantity=4, difference=0,
            status=REC_REVIEW, confidence=None,
            details={"reason": "no reliable evidence"},
        )
    )
    db.commit()
    res = AlertRuleEngine(db).evaluate(store_id=store.id)
    rev = _alerts_of(db, ALERT_REVIEW_REQUIRED, store.id)
    assert len(rev) == 1
    assert rev[0].severity == SEV_LOW
    assert rev[0].product_id == product.id and rev[0].camera_id == camera.id
    assert rev[0].source_type == "reconciliation"
    assert rev[0].details["status"] == REC_REVIEW


def test_review_required_only_within_window(db, store, product, camera):
    old = _now() - timedelta(days=5)
    db.add(
        ReconciliationResult(
            store_id=store.id, product_id=product.id, camera_id=camera.id,
            observation_window_start=old - timedelta(hours=2),
            observation_window_end=old,
            database_quantity=4, ai_observed_quantity=4, difference=0,
            status=REC_REVIEW, confidence=None,
        )
    )
    db.commit()
    AlertRuleEngine(db).evaluate(store_id=store.id)
    assert _alerts_of(db, ALERT_REVIEW_REQUIRED, store.id) == []


# ---------------------------------------------------------------------------
# Rule engine: CAMERA_OFFLINE (stale-heartbeat foundation)
# ---------------------------------------------------------------------------

def test_camera_offline_for_stale_camera_only(db, store, plain_camera):
    idle_cam = _camera(db, store, "idle-b", config=None)
    _record_product(db, store, plain_camera, "Lays", bbox=[0, 0, 20, 20])  # fresh heartbeat for plain_camera
    res = AlertRuleEngine(db).evaluate(store_id=store.id)
    off = _alerts_of(db, ALERT_CAMERA_OFFLINE, store.id)
    assert len(off) == 1
    assert off[0].camera_id == idle_cam.id
    assert off[0].severity == SEV_MEDIUM
    assert off[0].details["proxy"]
    assert "simulated" in off[0].details["proxy"]
    assert off[0].details["last_observed_at"] is None


def test_inactive_camera_not_flagged_offline(db, store):
    inactive = _camera(db, store, "inactive", config=None, active=False)
    res = AlertRuleEngine(db).evaluate(store_id=store.id)
    assert res.generated == 0
    assert _alerts_of(db, ALERT_CAMERA_OFFLINE, store.id) == []
    assert inactive.is_active is False


def test_camera_scoped_evaluation(db, store, plain_camera):
    idle_cam = _camera(db, store, "idle-c", config=None)
    _record_product(db, store, plain_camera, "Lays", bbox=[0, 0, 20, 20])
    res = AlertRuleEngine(db).evaluate(store_id=store.id, camera_id=idle_cam.id)
    off = _alerts_of(db, ALERT_CAMERA_OFFLINE, store.id)
    assert len(off) == 1 and off[0].camera_id == idle_cam.id
    assert res.generated == 1


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def test_lifecycle_acknowledge_then_resolve(db, store, product, camera):
    a, _ = AlertService(db).create_alert(
        store_id=store.id, alert_type=ALERT_SHORTAGE, severity=SEV_LOW, title="T",
        product_id=product.id, camera_id=camera.id,
    )
    assert a.status == STATUS_OPEN and a.acknowledged_at is None
    svc = AlertService(db)
    a = svc.acknowledge(a)
    assert a.status == STATUS_ACKNOWLEDGED and a.acknowledged_at is not None
    a = svc.resolve(a)
    assert a.status == STATUS_RESOLVED and a.resolved_at is not None
    with pytest.raises(InvalidStatusTransitionError):
        svc.resolve(a)  # already terminal


def test_lifecycle_open_to_dismissed(db, store, product, camera):
    a, _ = AlertService(db).create_alert(
        store_id=store.id, alert_type=ALERT_EXPIRY, severity=SEV_HIGH, title="T",
        product_id=product.id,
    )
    svc = AlertService(db)
    a = svc.dismiss(a)
    assert a.status == STATUS_DISMISSED and a.dismissed_at is not None
    with pytest.raises(InvalidStatusTransitionError):
        svc.acknowledge(a)


def test_invalid_transitions_rejected(db, store, product, camera):
    svc = AlertService(db)
    a, _ = svc.create_alert(
        store_id=store.id, alert_type=ALERT_SHORTAGE, severity=SEV_LOW, title="T",
        product_id=product.id, camera_id=camera.id,
    )
    with pytest.raises(InvalidStatusTransitionError):
        svc.change_status(a, "BOGUS")
    svc.acknowledge(a)
    with pytest.raises(InvalidStatusTransitionError):
        svc.acknowledge(a)  # ACKNOWLEDGED -> ACKNOWLEDGED not allowed
    with pytest.raises(InvalidStatusTransitionError):
        svc.change_status(a, STATUS_OPEN)  # cannot reopen


def test_resolved_alert_allows_new_alert_when_condition_returns(db, store, plain_camera, product):
    _set_inventory(db, store, product, 9)
    _record_product(db, store, plain_camera, "Lays", bbox=[0, 0, 20, 20], conf=0.9)
    AlertRuleEngine(db).evaluate(store_id=store.id)
    (a,) = _alerts_of(db, ALERT_SHORTAGE, store.id)
    AlertService(db).resolve(a)

    res = AlertRuleEngine(db).evaluate(store_id=store.id)
    assert res.generated == 1  # terminal alert does not block a new alert
    alerts = _alerts_of(db, ALERT_SHORTAGE, store.id)
    assert len(alerts) == 2
    assert {x.status for x in alerts} == {STATUS_RESOLVED, STATUS_OPEN}


def test_acknowledged_alert_deduplicates_but_resolved_does_not(db, store, product, camera):
    svc = AlertService(db)
    a, _ = svc.create_alert(
        store_id=store.id, alert_type=ALERT_SURPLUS, severity=SEV_LOW, title="T",
        product_id=product.id,
    )
    svc.acknowledge(a)
    _, created = svc.create_alert(
        store_id=store.id, alert_type=ALERT_SURPLUS, severity=SEV_LOW, title="T",
        product_id=product.id,
    )
    assert created is False  # ACKNOWLEDGED still deduplicates
    svc.resolve(a)
    _, created = svc.create_alert(
        store_id=store.id, alert_type=ALERT_SURPLUS, severity=SEV_LOW, title="T",
        product_id=product.id,
    )
    assert created is True  # RESOLVED is terminal -> new alert


# ---------------------------------------------------------------------------
# The alert layer NEVER mutates inventory / batches / bills / sales
# ---------------------------------------------------------------------------

def test_evaluate_and_lifecycle_never_mutate_business_data(db, store, camera, shelf, product):
    inv = _set_inventory(db, store, product, 4)
    now = _now()
    db.add(InventoryMovement(store_id=store.id, product_id=product.id, quantity_change=-1, movement_type="SALE", timestamp_utc=now))
    batch = Batch(store_id=store.id, product_id=product.id, batch_number="B-OK", expiry_date=date(2030, 1, 1), expiry_date_precision=BATCH_PRECISION_DAY, quantity=4)
    db.add(batch)
    db.commit()
    sale = Sale(store_id=store.id, sale_timestamp_utc=now, subtotal=Decimal("10.00"), tax_total=Decimal("0"), total=Decimal("10.00"))
    db.add(sale)
    db.commit()
    db.add(Bill(store_id=store.id, bill_number="BILL-1", sale_id=sale.id, subtotal=Decimal("10.00"), tax_total=Decimal("0"), total=Decimal("10.00")))
    db.commit()

    before = {
        "inventory": _count(db, Inventory),
        "movements": _count(db, InventoryMovement),
        "batches": _count(db, Batch),
        "bills": _count(db, Bill),
        "sales": _count(db, Sale),
    }
    inv_qty_before = inv.quantity

    _record_product(db, store, camera, "Lays", bbox=[60, 0, 80, 20], conf=0.9)
    res = AlertRuleEngine(db).evaluate(store_id=store.id)
    assert res.generated >= 1

    svc = AlertService(db)
    for a in res.alerts:
        svc.acknowledge(a)
        svc.resolve(a)

    assert _count(db, Inventory) == before["inventory"]
    assert _count(db, InventoryMovement) == before["movements"]
    assert _count(db, Batch) == before["batches"]
    assert _count(db, Bill) == before["bills"]
    assert _count(db, Sale) == before["sales"]
    db.refresh(inv)
    assert inv.quantity == inv_qty_before


# ---------------------------------------------------------------------------
# HTTP API
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(session_factory):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.deps import get_db

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


def test_api_create_get_list_patch(db, client, store, product, camera):
    payload = {
        "store_id": str(store.id),
        "alert_type": ALERT_SHORTAGE,
        "severity": SEV_MEDIUM,
        "title": "Manual check",
        "message": "Check stock",
        "camera_id": str(camera.id),
        "product_id": str(product.id),
        "confidence": 0.85,
        "details": {"note": "manual"},
    }
    r = client.post("/api/alerts", json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == STATUS_OPEN
    assert body["store_id"] == str(store.id)
    alert_id = body["id"]

    got = client.get(f"/api/alerts/{alert_id}")
    assert got.status_code == 200
    assert got.json()["title"] == "Manual check"

    missing = client.get("/api/alerts/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404

    patched = client.patch(
        f"/api/alerts/{alert_id}",
        json={"title": "Renamed", "status": STATUS_RESOLVED, "severity": SEV_HIGH},
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "Renamed"
    assert patched.json()["severity"] == SEV_HIGH
    assert patched.json()["status"] == STATUS_OPEN  # metadata-only: status untouched

    bad_sev = client.patch(f"/api/alerts/{alert_id}", json={"severity": "PUCE"})
    assert bad_sev.status_code == 422

    listing = client.get(f"/api/alerts?alert_type={ALERT_SHORTAGE}&severity={SEV_HIGH}")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1


def test_api_lifecycle_endpoints(db, client, store, product, camera):
    r = client.post(
        "/api/alerts",
        json={"store_id": str(store.id), "alert_type": ALERT_EXPIRY, "severity": SEV_HIGH, "title": "Exp"},
    )
    alert_id = r.json()["id"]

    ack = client.post(f"/api/alerts/{alert_id}/acknowledge")
    assert ack.status_code == 200 and ack.json()["status"] == STATUS_ACKNOWLEDGED

    res = client.post(f"/api/alerts/{alert_id}/resolve")
    assert res.status_code == 200 and res.json()["status"] == STATUS_RESOLVED

    again = client.post(f"/api/alerts/{alert_id}/resolve")
    assert again.status_code == 422  # terminal

    dismiss = client.post(f"/api/alerts/{alert_id}/dismiss")
    assert dismiss.status_code == 422  # open? no — already RESOLVED, terminal

    missing = client.post("/api/alerts/00000000-0000-0000-0000-000000000000/acknowledge")
    assert missing.status_code == 404


def test_api_dismiss_endpoint(db, client, store, product, camera):
    r = client.post(
        "/api/alerts",
        json={"store_id": str(store.id), "alert_type": ALERT_SHORTAGE, "severity": SEV_LOW, "title": "T"},
    )
    alert_id = r.json()["id"]
    d = client.post(f"/api/alerts/{alert_id}/dismiss")
    assert d.status_code == 200 and d.json()["status"] == STATUS_DISMISSED
    assert d.json()["dismissed_at"] is not None


def test_api_evaluate_generates_and_reports(db, client, store, plain_camera, product):
    _set_inventory(db, store, product, 9)
    _record_product(db, store, plain_camera, "Lays", bbox=[0, 0, 20, 20], conf=0.9)
    body = {
        "store_id": str(store.id),
        "hours": 24,
        "alert_confidence_threshold": 0.5,
    }
    r = client.post("/api/alerts/evaluate", json=body)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["store_id"] == str(store.id)
    assert res["hours"] == 24
    assert res["generated"] == 1
    assert res["updated"] == 0
    assert len(res["alerts"]) == 1
    assert res["alerts"][0]["alert_type"] == ALERT_SHORTAGE
    assert "evaluated_at" in res


def test_api_evaluate_never_mutates_inventory(db, client, store, plain_camera, product):
    inv = _set_inventory(db, store, product, 6)
    now = _now()
    db.add(InventoryMovement(store_id=store.id, product_id=product.id, quantity_change=-1, movement_type="SALE", timestamp_utc=now))
    db.add(Batch(store_id=store.id, product_id=product.id, batch_number="B-OK", expiry_date=date(2031, 1, 1), expiry_date_precision=BATCH_PRECISION_DAY, quantity=6))
    db.add(Sale(store_id=store.id, sale_timestamp_utc=now, subtotal=Decimal("10.00"), tax_total=Decimal("0"), total=Decimal("10.00")))
    db.commit()
    db.add(Bill(store_id=store.id, bill_number="BILL-2", subtotal=Decimal("10.00"), tax_total=Decimal("0"), total=Decimal("10.00")))
    db.commit()
    before = {
        "inventory": _count(db, Inventory),
        "movements": _count(db, InventoryMovement),
        "batches": _count(db, Batch),
        "bills": _count(db, Bill),
        "sales": _count(db, Sale),
    }

    _record_product(db, store, plain_camera, "Lays", bbox=[0, 0, 20, 20], conf=0.9)
    r = client.post("/api/alerts/evaluate", json={"store_id": str(store.id)})
    assert r.status_code == 200
    assert r.json()["generated"] >= 1

    assert _count(db, Inventory) == before["inventory"]
    assert _count(db, InventoryMovement) == before["movements"]
    assert _count(db, Batch) == before["batches"]
    assert _count(db, Bill) == before["bills"]
    assert _count(db, Sale) == before["sales"]
    db.refresh(inv)
    assert inv.quantity == 6


def test_api_list_filtering_status_and_pagination(db, client, store, product, camera):
    cameras = []
    for i in range(4):
        cameras.append(_camera(db, store, f"cam-{i}", config=None))
    for idx, tup in enumerate(
        [(ALERT_SHORTAGE, SEV_MEDIUM), (ALERT_SURPLUS, SEV_LOW), (ALERT_EXPIRY, SEV_HIGH), (ALERT_SHORTAGE, SEV_HIGH)]
    ):
        t, sev = tup
        client.post(
            "/api/alerts",
            json={
                "store_id": str(store.id),
                "alert_type": t,
                "severity": sev,
                "title": f"T-{t}-{sev}",
                "camera_id": str(cameras[idx].id),
            },
        )
    status_res = client.get("/api/alerts?status=OPEN")
    assert status_res.json()["total"] == 4

    type_res = client.get("/api/alerts?alert_type=SHORTAGE")
    assert type_res.json()["total"] == 2

    sev_res = client.get("/api/alerts?severity=HIGH")
    assert sev_res.json()["total"] == 2

    page = client.get("/api/alerts?limit=2&offset=0")
    assert page.status_code == 200
    assert page.json()["total"] == 4 and len(page.json()["items"]) == 2

    bad = client.get("/api/alerts?alert_type=NOPE")
    assert bad.status_code == 422


def test_api_create_validation_422(db, client, store):
    r = client.post("/api/alerts", json={"store_id": str(store.id), "alert_type": "BOGUS", "severity": SEV_LOW, "title": "x"})
    assert r.status_code == 422
    r = client.post("/api/alerts", json={"store_id": str(store.id), "alert_type": ALERT_SHORTAGE, "severity": "RED", "title": "x"})
    assert r.status_code == 422