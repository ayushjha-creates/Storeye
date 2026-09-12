"""Milestone 8 tests: AI Observation layer.

Integration tests run against the isolated PostgreSQL database (storeye_test).
They verify that observations can be recorded/queried for products, persons,
OCR text, and expiry metadata — and critically that recording observations
NEVER modifies inventory or auto-creates batches.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import Batch, Camera, Inventory, InventoryMovement, Observation, Product, Store
from app.services.observations import (
    ObservationService,
    from_shelf_detection,
    from_person_detection,
    from_tracked_person,
    from_ocr_result,
    from_parsed_metadata,
)
from app.services.observations.errors import ValidationError
from app.services.product.expiry_parser import ParsedProductMetadata
from app.services.inventory import BatchService
from app.services.inventory.errors import EntityNotFoundError

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
    s = Store(name="Obs Store", timezone="Asia/Kolkata")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@pytest.fixture()
def product(db, store) -> Product:
    p = Product(store_id=store.id, sku="OBS-P1", name="Observed Product", selling_price=50)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@pytest.fixture()
def camera(db, store) -> Camera:
    c = Camera(name="obs-cam-1", store_id=store.id)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _obs(db):
    return ObservationService(db)


def _set_inventory(db, store, product, qty):
    inv = db.scalar(select(Inventory).where(Inventory.store_id == store.id, Inventory.product_id == product.id))
    if inv is None:
        inv = Inventory(store_id=store.id, product_id=product.id, quantity=qty)
        db.add(inv)
    else:
        inv.quantity = qty
    db.commit()
    db.refresh(inv)
    return inv


def _inv_qty(db, store, product):
    inv = db.scalar(select(Inventory).where(Inventory.store_id == store.id, Inventory.product_id == product.id))
    return inv.quantity if inv else 0


def _batch_count(db):
    return db.query(Batch).count()


def _observation_count(db):
    return db.query(Observation).count()


# ---------------------------------------------------------------------------
# 1. Product observation creation
# ---------------------------------------------------------------------------
def test_product_observation_created_with_product_id(db, store, product, camera):
    svc = _obs(db)
    obs = svc.record_product_observation(
        store_id=store.id, camera_id=camera.id, product_id=product.id,
        confidence=0.91, bbox=[10, 20, 130, 240], source="files/test_a.mp4", frame_number=14,
    )
    assert obs.id is not None
    assert obs.observation_type == "PRODUCT"
    assert obs.product_id == product.id
    assert obs.store_id == store.id
    assert obs.confidence == 0.91
    assert obs.source == "files/test_a.mp4"


# ---------------------------------------------------------------------------
# 2. Product observation without product_id (uncertain detection)
# ---------------------------------------------------------------------------
def test_product_observation_without_product_id(db, store, camera):
    svc = _obs(db)
    obs = svc.record_product_observation(
        store_id=store.id, camera_id=camera.id, product_id=None,
        confidence=0.55, bbox=[0, 0, 10, 10],
    )
    assert obs.product_id is None
    assert obs.observation_type == "PRODUCT"


# ---------------------------------------------------------------------------
# 3. Person observation with anonymous track_id
# ---------------------------------------------------------------------------
def test_person_observation_anonymous_track_id(db, store, camera):
    svc = _obs(db)
    obs = svc.record_person_observation(
        store_id=store.id, camera_id=camera.id, track_id=7,
        confidence=0.9, bbox=[1, 1, 50, 80], source="files/cam_a.mp4",
    )
    assert obs.observation_type == "PERSON"
    assert obs.track_id == 7
    # Anonymous: no face/identity columns should ever be populated.
    assert getattr(obs, "text", None) is None


# ---------------------------------------------------------------------------
# 4. OCR text observation
# ---------------------------------------------------------------------------
def test_ocr_text_observation(db, store, camera):
    svc = _obs(db)
    obs = svc.record_text_observation(
        store_id=store.id, camera_id=camera.id, text="EXP 12/2026 MRP 150",
        confidence=0.8, bbox=[0, 0, 5, 5],
    )
    assert obs.observation_type == "TEXT"
    assert obs.text == "EXP 12/2026 MRP 150"
    assert obs.confidence == 0.8


# ---------------------------------------------------------------------------
# 5. Expiry metadata observation
# ---------------------------------------------------------------------------
def test_expiry_metadata_observation(db, store, product, camera):
    meta = ParsedProductMetadata(
        expiry_date=date(2026, 12, 31),
        expiry_date_precision="day",
        batch_number="OBSBATCH01",
        mrp=150,
        raw_text="EXP 31/12/2026 BATCH OBSBATCH01 MRP 150",
        confidence=0.85,
        warnings=["low contrast"],
    )
    svc = _obs(db)
    obs = svc.record_expiry_metadata_observation(
        store_id=store.id, camera_id=camera.id, source_observation_id=None,
        raw_text=meta.raw_text, confidence=meta.confidence,
        expiry_date=meta.expiry_date, expiry_date_precision=meta.expiry_date_precision,
        manufacturing_date=meta.manufacturing_date, batch_number=meta.batch_number,
        mrp=meta.mrp, warnings=meta.warnings,
    )
    assert obs.observation_type == "EXPIRY_METADATA"
    assert obs.details["expiry_date"] == "2026-12-31"
    assert obs.details["batch_number"] == "OBSBATCH01"
    assert obs.details["warnings"] == ["low contrast"]


# ---------------------------------------------------------------------------
# 6 & 7. Bounding box and confidence persistence
# ---------------------------------------------------------------------------
def test_bbox_and_confidence_persisted(db, store, camera):
    svc = _obs(db)
    obs = svc.record_text_observation(
        store_id=store.id, camera_id=camera.id, text="x", confidence=0.37, bbox=[1.5, 2.5, 3.5, 4.75],
    )
    assert obs.bbox == [1.5, 2.5, 3.5, 4.75]
    assert obs.confidence == 0.37


# ---------------------------------------------------------------------------
# 8. Camera association
# ---------------------------------------------------------------------------
def test_camera_association_and_query(db, store, camera):
    svc = _obs(db)
    obs = svc.record_product_observation(
        store_id=store.id, camera_id=camera.id, product_id=None,
        confidence=0.6, bbox=[0, 0, 1, 1],
    )
    results = svc.observations_for_camera(camera.id)
    assert any(o.id == obs.id for o in results)
    assert all(o.camera_id == camera.id for o in results)


# ---------------------------------------------------------------------------
# 9. Store association and query
# ---------------------------------------------------------------------------
def test_store_association_and_query(db, store, camera):
    svc = _obs(db)
    obs = svc.record_product_observation(
        store_id=store.id, camera_id=camera.id, product_id=None,
        confidence=0.6, bbox=[0, 0, 1, 1],
    )
    results = svc.observations_for_store(store.id)
    assert any(o.id == obs.id for o in results)


# ---------------------------------------------------------------------------
# 10. Time-range querying
# ---------------------------------------------------------------------------
def test_time_range_query(db, store, camera):
    svc = _obs(db)
    base = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
    o1 = svc.record_product_observation(store_id=store.id, camera_id=camera.id, product_id=None, confidence=0.5, bbox=[0,0,1,1], observed_at=base)
    o2 = svc.record_product_observation(store_id=store.id, camera_id=camera.id, product_id=None, confidence=0.5, bbox=[0,0,1,1], observed_at=base + timedelta(hours=2))
    o3 = svc.record_product_observation(store_id=store.id, camera_id=camera.id, product_id=None, confidence=0.5, bbox=[0,0,1,1], observed_at=base + timedelta(days=5))
    results = svc.observations_for_time_range(base, base + timedelta(hours=3))
    ids = {o.id for o in results}
    assert o1.id in ids and o2.id in ids and o3.id not in ids


# ---------------------------------------------------------------------------
# 11. Observation-type querying
# ---------------------------------------------------------------------------
def test_observation_type_query(db, store, camera):
    svc = _obs(db)
    svc.record_person_observation(store_id=store.id, camera_id=camera.id, track_id=1, confidence=0.9, bbox=[0,0,1,1])
    svc.record_text_observation(store_id=store.id, camera_id=camera.id, text="hello", confidence=0.9, bbox=[0,0,1,1])
    people = svc.observations_by_type("PERSON")
    assert len(people) == 1 and people[0].observation_type == "PERSON"
    texts = svc.observations_by_type("TEXT")
    assert len(texts) == 1 and texts[0].text == "hello"
    with pytest.raises(ValidationError):
        svc.observations_by_type("BOGUS")


# ---------------------------------------------------------------------------
# 12. Product querying
# ---------------------------------------------------------------------------
def test_product_query(db, store, product, camera):
    svc = _obs(db)
    svc.record_product_observation(store_id=store.id, camera_id=camera.id, product_id=product.id, confidence=0.8, bbox=[0,0,1,1])
    svc.record_product_observation(store_id=store.id, camera_id=camera.id, product_id=None, confidence=0.8, bbox=[0,0,1,1])
    results = svc.observations_for_product(product.id)
    assert len(results) == 1
    assert all(o.product_id == product.id for o in results)


# ---------------------------------------------------------------------------
# 13. Track ID querying
# ---------------------------------------------------------------------------
def test_track_id_query(db, store, camera):
    svc = _obs(db)
    svc.record_person_observation(store_id=store.id, camera_id=camera.id, track_id=3, confidence=0.9, bbox=[0,0,1,1], frame_number=0)
    svc.record_person_observation(store_id=store.id, camera_id=camera.id, track_id=3, confidence=0.8, bbox=[0,0,1,1], frame_number=1)
    svc.record_person_observation(store_id=store.id, camera_id=camera.id, track_id=4, confidence=0.7, bbox=[0,0,1,1], frame_number=0)
    results = svc.observations_for_track(3)
    assert len(results) == 2
    assert all(o.track_id == 3 for o in results)


# ---------------------------------------------------------------------------
# 14. Invalid foreign keys (digest + DB-level rejection)
# ---------------------------------------------------------------------------
def test_invalid_foreign_keys(db, store, camera):
    svc = _obs(db)
    bad = "00000000-0000-0000-0000-000000000000"
    from sqlalchemy.exc import IntegrityError
    with pytest.raises((IntegrityError, EntityNotFoundError)):
        svc.record_product_observation(store_id=bad, camera_id=camera.id, product_id=None, confidence=0.6, bbox=[0,0,1,1])
    # The failed write must be rolled back (no partial row left).
    assert _observation_count(db) == 0


def test_bad_observation_type_rejected(db, store, camera):
    svc = _obs(db)
    with pytest.raises(ValidationError):
        svc.record_observation(observation_type="ALIEN", store_id=store.id)


def test_confidence_out_of_range_rejected(db, store, camera):
    svc = _obs(db)
    with pytest.raises(ValidationError):
        svc.record_person_observation(store_id=store.id, camera_id=camera.id, track_id=1, confidence=1.5, bbox=[0,0,1,1])


# ---------------------------------------------------------------------------
# 15. No inventory modification after AI observation (MANDATORY)
# ---------------------------------------------------------------------------
def test_no_inventory_modification_after_observation(db, store, product, camera):
    _set_inventory(db, store, product, 20)
    assert _inv_qty(db, store, product) == 20

    before_movements = db.query(InventoryMovement).count()

    svc = _obs(db)
    # AI "detects" five products.
    for _ in range(5):
        svc.record_product_observation(
            store_id=store.id, camera_id=camera.id, product_id=product.id,
            confidence=0.9, bbox=[0, 0, 10, 10],
        )
    # AI OBSERVES a person, some OCR text, and expiry metadata.
    svc.record_person_observation(store_id=store.id, camera_id=camera.id, track_id=1, confidence=0.8, bbox=[0,0,10,10])
    svc.record_text_observation(store_id=store.id, camera_id=camera.id, text="whatever", confidence=0.8, bbox=[0,0,10,10])
    svc.record_expiry_metadata_observation(store_id=store.id, raw_text="EXP 12/2026", confidence=0.8, expiry_date=date(2026,12,31))

    # Inventory unchanged.
    assert _inv_qty(db, store, product) == 20
    # No inventory movements were created by observations.
    after_movements = db.query(InventoryMovement).count()
    assert after_movements == before_movements


# ---------------------------------------------------------------------------
# 16. No automatic batch creation after expiry observation (MANDATORY)
# ---------------------------------------------------------------------------
def test_no_automatic_batch_creation_after_expiry_observation(db, store, product, camera):
    before_batches = _batch_count(db)
    svc = _obs(db)
    svc.record_expiry_metadata_observation(
        store_id=store.id, camera_id=camera.id, raw_text="BATCH X MRP 150 EXP 12/2027",
        confidence=0.85, expiry_date=date(2027, 12, 31), batch_number="X", mrp=150,
    )
    assert _batch_count(db) == before_batches
    assert _observation_count(db) == 1

    # Batch is only created by the explicit business operation.
    b = BatchService(db).create_batch(
        store_id=store.id, product_id=product.id, batch_number="X",
        expiry_date=date(2027, 12, 31), mrp=150, quantity=0,
    )
    assert _batch_count(db) == before_batches + 1


# ---------------------------------------------------------------------------
# Adapter tests (constructed outputs, no AI inference)
# ---------------------------------------------------------------------------
class _Stub:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_adapter_from_shelf_detection(db, store, product, camera):
    d = _Stub(class_id=3, class_name="biscuit", confidence=0.92, bbox_xyxy=[1, 2, 3, 4])
    draft = from_shelf_detection(d, source="files/axial.mp4", store_id=store.id, camera_id=camera.id, product_id=product.id)
    obs = _obs(db).record_observation(**draft.to_kwargs())
    assert obs.observation_type == "PRODUCT"
    assert obs.product_id == product.id
    assert obs.details["class_name"] == "biscuit"
    assert obs.bbox == [1.0, 2.0, 3.0, 4.0]


def test_adapter_from_person_detection_and_tracked(db, store, camera):
    svc = _obs(db)
    raw = _Stub(class_id=0, class_name="person", confidence=0.9, bbox_xyxy=[0, 0, 40, 90])
    from_person_detection(raw, store_id=store.id, camera_id=camera.id)
    tracked = _Stub(track_id=5, class_id=0, class_name="person", confidence=0.88, bbox_xyxy=[0, 0, 40, 90])
    obs = svc.record_observation(**from_tracked_person(tracked, store_id=store.id, camera_id=camera.id).to_kwargs())
    assert obs.track_id == 5
    assert obs.observation_type == "PERSON"


def test_adapter_from_ocr_and_parsed(db, store, camera):
    svc = _obs(db)
    ocr_item = _Stub(text="LOT 42", confidence=0.81, bbox_xyxy=[0, 0, 5, 5])
    text_obs = svc.record_observation(**from_ocr_result(ocr_item, store_id=store.id, camera_id=camera.id).to_kwargs())
    meta = ParsedProductMetadata(
        expiry_date=date(2026, 10, 31), expiry_date_precision="day",
        batch_number="LOT 42", mrp=None, raw_text="LOT 42", confidence=0.8, warnings=["date only month"],
    )
    exp = svc.record_observation(
        **from_parsed_metadata(meta, store_id=store.id, camera_id=camera.id, source_observation_id=text_obs.id).to_kwargs()
    )
    assert exp.source_observation_id == text_obs.id
    assert exp.details["batch_number"] == "LOT 42"