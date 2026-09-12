"""Milestone 17 tests: Smart Batch Receiving + Close-Up OCR.

Integration tests against the isolated storeye_test database. They verify:

    * scanning is READ-ONLY (products/inventory/batches/movements unchanged);
    * barcode resolves against the LOCAL product catalog only — unknown
      barcodes surface a "not found / select a product" state, never a guess;
    * pre-OCR quality gate rejects undecodable/too-small images (422);
    * confirm is ATOMIC — batch + inventory + movement in one transaction,
      reusing BatchService/InventoryService validation and semantics;
    * confirm reuses an existing (store, product, batch_number) batch instead
      of duplicating it;
    * the HTTP contract works end-to-end (multipart scan upload, confirm).

Component-level (no DB) tests at the top exercise the scan pipeline with a
deterministic fake barcode decoder and a stub OCR processor.
"""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from uuid import UUID

import numpy as np
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models import BATCH_PRECISION_DAY, Batch, Inventory, InventoryMovement, Product, Store
from app.services.batch_intake import (
    BarcodeUnavailableError,
    BatchIntakeService,
    DecodedBarcode,
    FakeBarcodeDecoder,
    ImageDecodeError,
    ImageQualityError,
    PackageOCRProcessor,
    PyZbarBarcodeDecoder,
)
from app.services.inventory.errors import EntityNotFoundError, ValidationError
from app.services.vision.ocr import OCRResult

pytestmark = pytest.mark.pg

TEST_DB_URL = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg2://storeye@localhost:5433/storeye_test")


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
    s = Store(name="Intake Store", timezone="Asia/Kolkata")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@pytest.fixture()
def product(db, store) -> Product:
    p = Product(
        store_id=store.id,
        sku="COMPLAN",
        name="Complan",
        selling_price=150,
        barcode="8901234567890",
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _empty_ocr():
    return OCRResult()


def _service(db, *, barcode=None, ocr_any=None):
    ocr = ocr_any or PackageOCRProcessor(ocr_factory=_empty_ocr)
    return BatchIntakeService(
        db,
        barcode_decoder=FakeBarcodeDecoder(
            [DecodedBarcode(data=barcode, symbology="CODE39", confidence=1.0)]
            if barcode
            else []
        ),
        ocr_processor=ocr,
    )


def _image_bytes(min_side: int = 640, long_side: int = 1200) -> bytes:
    import cv2

    img = np.full((min_side, long_side, 3), 240, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


def _count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


# ---------------------------------------------------------------------------
# 1. Scan pipeline (component, no database writes; fake barcode/OCR)
# ---------------------------------------------------------------------------

def test_signature_unusable_image_rejected():
    svc = _service(None)
    with pytest.raises(ImageDecodeError):
        svc.scan_package(b"definitely-not-an-image")


def test_signature_too_small_image_rejected():
    svc = _service(None)
    import cv2

    img = np.full((100, 100, 3), 0, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    with pytest.raises(ImageQualityError):
        svc.scan_package(buf.tobytes())


def test_scan_with_no_barcode_and_no_ocr_text_is_not_acceptable():
    svc = _service(None)
    scan = svc.scan_package(_image_bytes())
    assert scan.acceptable is False
    assert "Unable to confidently read" in scan.reason
    assert scan.candidate.barcode is None
    assert scan.candidate.product_found is False


def test_scan_with_barcode_but_no_ocr_is_acceptable_and_guides_product_selection(db, store):
    svc = _service(db, barcode="8901234567890")
    scan = svc.scan_package(_image_bytes(), store_id=store.id)
    assert scan.acceptable is True
    assert scan.candidate.barcode == "8901234567890"
    assert scan.candidate.barcode_read is True
    assert scan.candidate.product_found is False
    assert "Select a product to continue" in scan.reason


def test_scan_parses_expiry_metadata_from_stub_ocr_into_candidate():
    class StubOcr:
        def extract_text(self, image_bgr):
            return OCRResult(
                items=[],
            )

    class TextOcr:
        def extract_text(self, image_bgr):
            from app.services.vision.ocr import OCRTextItem

            return OCRResult(
                items=[
                    OCRTextItem(text="EXP: 15/12/2026", confidence=0.97, bbox_xyxy=[0, 0, 100, 20]),
                    OCRTextItem(text="BATCH: M24031", confidence=0.92, bbox_xyxy=[0, 25, 100, 45]),
                    OCRTextItem(text="MRP: 14.00", confidence=0.88, bbox_xyxy=[0, 50, 100, 70]),
                ]
            )

    svc = _service(
        None,
        ocr_any=PackageOCRProcessor(ocr_factory=TextOcr),
    )
    scan = svc.scan_package(_image_bytes())
    assert scan.acceptable is True
    cand = scan.candidate
    assert cand.expiry_date == date(2026, 12, 15)
    assert cand.batch_number == "M24031"
    assert cand.mrp == Decimal("14.00")
    assert cand.labels_found == ["expiry", "batch", "mrp"]


def test_local_barcode_decoding_roundtrip():
    """The real pyzbar/zbar decoder reads our offline Code-39 fixture image."""
    from tests._barcode_fixture import code39_image

    try:
        decoder = PyZbarBarcodeDecoder()
    except BarcodeUnavailableError:
        pytest.skip("system zbar/pyzbar not available in this environment")

    reads = decoder.decode(code39_image("M24031"))
    assert reads and reads[0].data == "M24031"
    assert reads[0].symbology.upper() == "CODE39"


# ---------------------------------------------------------------------------
# 2. Scan is read-only (no DB mutation)
# ---------------------------------------------------------------------------

def test_scan_never_mutates_business_tables(db, store, product):
    before = {
        "products": _count(db, Product),
        "inventory": _count(db, Inventory),
        "batches": _count(db, Batch),
        "movements": _count(db, InventoryMovement),
    }
    svc = _service(db, barcode=product.barcode)
    scan = svc.scan_package(_image_bytes(), store_id=store.id)
    assert scan.acceptable is True
    assert scan.candidate.product_id == str(product.id)
    assert scan.candidate.product_found is True
    after = {
        "products": _count(db, Product),
        "inventory": _count(db, Inventory),
        "batches": _count(db, Batch),
        "movements": _count(db, InventoryMovement),
    }
    assert after == before
    assert scan.candidate.product_name == product.name


def test_scan_resolves_barcode_to_local_product(db, store, product):
    svc = _service(db, barcode=product.barcode)
    scan = svc.scan_package(_image_bytes(), store_id=store.id)
    assert scan.candidate.barcode == product.barcode
    assert scan.candidate.product_id == str(product.id)


def test_scan_unknown_barcode_reports_not_found_without_creating_product(db, store, product):
    svc = _service(db, barcode="0000000000000")
    scan = svc.scan_package(_image_bytes(), store_id=store.id)
    assert scan.acceptable is True
    assert scan.candidate.barcode == "0000000000000"
    assert scan.candidate.product_found is False
    assert scan.candidate.product_id is None


def test_scan_barcode_outside_store_is_not_matched(db, store, product):
    other = Store(name="Other Store", timezone="Asia/Kolkata")
    db.add(other)
    db.commit()
    db.refresh(other)
    svc = _service(db, barcode=product.barcode)
    scan = svc.scan_package(_image_bytes(), store_id=other.id)
    assert scan.candidate.product_found is False


def test_scan_without_store_scopes_to_any_store(db, product):
    svc = _service(db, barcode=product.barcode)
    scan = svc.scan_package(_image_bytes())
    assert scan.candidate.product_found is True


# ---------------------------------------------------------------------------
# 3. Confirm: atomic, human-confirmed, reuses domain services
# ---------------------------------------------------------------------------

def test_confirm_tight_without_batch_number_creates_atomic_receipt(db, store, product):
    svc = _service(db)
    batch, movement = svc.confirm_receipt(
        store_id=store.id,
        product_id=product.id,
        quantity=5,
        manufacturing_date=date(2026, 3, 12),
        expiry_date=date(2026, 12, 31),
        mrp=Decimal("150.00"),
        reference="PO-1",
    )
    assert _count(db, Batch) == 1
    assert _count(db, Inventory) == 1
    assert _count(db, InventoryMovement) == 1

    inv = db.scalar(select(Inventory))
    assert inv.quantity == 5
    assert batch.quantity == 5
    assert movement.movement_type == "PURCHASE"
    assert movement.quantity_change == 5
    assert movement.batch_id == batch.id
    assert batch.expiry_date == date(2026, 12, 31)
    assert batch.manufacturing_date == date(2026, 3, 12)
    assert batch.mrp == Decimal("150.00")
    assert batch.expiry_date_precision == BATCH_PRECISION_DAY


def test_confirm_reuses_existing_batch_number(db, store, product):
    svc = _service(db)
    first = svc.confirm_receipt(
        store_id=store.id, product_id=product.id, quantity=3, batch_number="B24031"
    )[0]
    db.commit()
    second = svc.confirm_receipt(
        store_id=store.id, product_id=product.id, quantity=2, batch_number="B24031"
    )[0]
    assert second.id == first.id
    assert _count(db, Batch) == 1
    inv = db.scalar(select(Inventory))
    assert inv.quantity == 5
    assert second.quantity == 5


def test_confirm_distinct_batch_numbers_create_distinct_rows(db, store, product):
    svc = _service(db)
    svc.confirm_receipt(
        store_id=store.id, product_id=product.id, quantity=2, batch_number="B1"
    )
    svc.confirm_receipt(
        store_id=store.id, product_id=product.id, quantity=3, batch_number="B2"
    )
    assert _count(db, Batch) == 2
    inv = db.scalar(select(Inventory))
    assert inv.quantity == 5


def test_confirm_atomic_rollback_when_movement_fails(db, store, product, monkeypatch):
    from app.services.inventory.inventory_service import InventoryService

    svc = _service(db)

    def boom(self, **kwargs):
        raise RuntimeError("inventory mutation failed mid-flight")

    monkeypatch.setattr(InventoryService, "receive_stock", boom)
    with pytest.raises(RuntimeError):
        svc.confirm_receipt(
            store_id=store.id, product_id=product.id, quantity=4, batch_number="ROLLBACK"
        )
    # Nothing persisted: no batch, no inventory, no movement.
    assert _count(db, Batch) == 0
    assert _count(db, Inventory) == 0
    assert _count(db, InventoryMovement) == 0


def test_confirm_rejects_quantity_zero_or_negative(db, store, product):
    svc = _service(db)
    with pytest.raises(ValidationError):
        svc.confirm_receipt(store_id=store.id, product_id=product.id, quantity=0)
    with pytest.raises(ValidationError):
        svc.confirm_receipt(store_id=store.id, product_id=product.id, quantity=-1)


def test_confirm_rejects_invalid_dates_and_mrp(db, store, product):
    svc = _service(db)
    with pytest.raises(ValidationError):
        svc.confirm_receipt(
            store_id=store.id,
            product_id=product.id,
            quantity=1,
            manufacturing_date=date(2026, 12, 31),
            expiry_date=date(2026, 1, 1),  # expiry before manufacturing
        )
    with pytest.raises(ValidationError):
        svc.confirm_receipt(
            store_id=store.id, product_id=product.id, quantity=1, mrp=Decimal("-5.00")
        )


def test_confirm_rejects_missing_store_or_product(db, store, product):
    svc = _service(db)
    with pytest.raises(EntityNotFoundError):
        svc.confirm_receipt(store_id=UUID(int=1), product_id=product.id, quantity=1)
    with pytest.raises(EntityNotFoundError):
        svc.confirm_receipt(store_id=store.id, product_id=UUID(int=2), quantity=1)


def test_confirm_month_precision_persisted(db, store, product):
    svc = _service(db)
    batch, _ = svc.confirm_receipt(
        store_id=store.id,
        product_id=product.id,
        quantity=2,
        batch_number="M42",
        expiry_date=date(2027, 9, 1),
        expiry_date_precision="month",
    )
    assert batch.expiry_date_precision == "month"


# ---------------------------------------------------------------------------
# 4. HTTP API
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(session_factory):
    from fastapi.testclient import TestClient

    from app.api.deps import get_db
    from app.main import app

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


def test_api_scan_unknown_image_returns_422(client):
    r = client.post(
        "/api/batch-intake/scan",
        files={"file": ("noop.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 422
    assert "must be an image" in r.json()["detail"][0]["msg"]


def test_api_scan_returns_candidate_without_mutating(client, db, store, product, monkeypatch):
    import app.api.routers.batch_intake as bi_module

    from app.services.batch_intake import PackageScan
    from app.services.product.expiry_parser import ParsedProductMetadata

    before = _count(db, Product) + _count(db, Batch) + _count(db, InventoryMovement)

    class FakeIntake:
        def __init__(self, session):
            self.session = session

        def scan_package(self, image_bytes, *, store_id=None):
            parsed = ParsedProductMetadata(
                expiry_date=date(2026, 12, 9),
                batch_number="M24031",
                mrp=Decimal("150.00"),
            )
            return PackageScan.from_parsed(
                parsed,
                barcode_read=True,
                barcode="8901234567890",
                product_id=str(product.id),
                product_name=product.name,
                product_sku=product.sku,
                product_found=True,
                store_id=str(store_id) if store_id else None,
            )

    monkeypatch.setattr(bi_module, "BatchIntakeService", FakeIntake)

    r = client.post(
        "/api/batch-intake/scan",
        data={"store_id": str(store.id)},
        files={"file": ("pack.jpg", _image_bytes(), "image/jpeg")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["acceptable"] is True
    cand = body["candidate"]
    assert cand["barcode"] == "8901234567890"
    assert cand["product_id"] == str(product.id)
    assert cand["expiry_date"] == "2026-12-09"
    assert cand["batch_number"] == "M24031"
    assert cand["labels_found"] == ["expiry", "batch", "mrp"]
    assert _count(db, Product) + _count(db, Batch) + _count(db, InventoryMovement) == before


def test_api_confirm_end_to_end(client, db, store, product):
    r = client.post(
        "/api/batch-intake/confirm",
        json={
            "store_id": str(store.id),
            "product_id": str(product.id),
            "quantity": 7,
            "batch_number": "API-BATCH",
            "manufacturing_date": "2026-02-01",
            "expiry_date": "2027-05-31",
            "mrp": "150.00",
            "reference": "scan-confirm-1",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["batch"]["batch_number"] == "API-BATCH"
    assert body["batch"]["expiry_date"] == "2027-05-31"
    assert body["batch"]["quantity"] == 7
    assert body["movement"]["quantity_change"] == 7
    assert body["movement"]["movement_type"] == "PURCHASE"
    assert _count(db, Batch) == 1
    assert _count(db, InventoryMovement) == 1


def test_api_confirm_rejects_zero_quantity(client, db, store, product):
    r = client.post(
        "/api/batch-intake/confirm",
        json={
            "store_id": str(store.id),
            "product_id": str(product.id),
            "quantity": 0,
        },
    )
    assert r.status_code == 422, r.text


def test_api_product_barcode_field_roundtrip(client, db, store):
    r = client.post(
        "/api/products",
        json={
            "store_id": str(store.id),
            "sku": "PACK-01",
            "name": "Packaged Goods",
            "selling_price": "10.00",
            "barcode": "8900000000007",
        },
    )
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert r.json()["barcode"] == "8900000000007"

    got = client.get(f"/api/products/{pid}")
    assert got.status_code == 200
    assert got.json()["barcode"] == "8900000000007"

    upd = client.patch(
        f"/api/products/{pid}",
        json={"barcode": "8900000000008"},
    )
    assert upd.status_code == 200
    assert upd.json()["barcode"] == "8900000000008"