"""M25 — REAL end-to-end USB intake test.

Full journey with NO mocks at the vision layer:
    phone photo (deterministic, offline-rendered, watermarked DEMO)
  -> watcher (stability + validation + content-hash)
  -> real zbar barcode decode
  -> real PaddleOCR text extraction
  -> real ExpiryParser
  -> catalog lookup against the SEEDED DEMO STORE
  -> REVIEW_REQUIRED candidate carrying barcode/product/expiry/batch/mrp
  -> human confirmation through the EXISTING M17 endpoint
  -> atomic batch + inventory movement commit.

The photo is deliberately generated offline (OpenCV), so the whole test is
deterministic and runs with no camera and no network.
"""

from __future__ import annotations

import datetime
import os
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.services.batch_intake.batch_intake_service import BatchIntakeService
from app.services.mobile_intake.demo_image import build_demo_intake_bytes
from app.services.mobile_intake.intake_models import JobState
from app.services.mobile_intake.intake_service import MobileIntakeService
from app.models import Product, Store
from scripts.seed_demo import seed_with_session

pytestmark = pytest.mark.pg

TEST_DB_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://storeye@localhost:5433/storeye_test",
)

AAS_ATTA_BARCODE = "8901063001015"


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DB_URL)
    yield eng
    eng.dispose()


@pytest.fixture()
def session_factory(engine):
    from app.db.base import Base

    with engine.begin() as conn:
        Base.metadata.drop_all(conn)
        Base.metadata.create_all(conn)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _real_scanner(session_factory):
    def scanner(data: bytes):
        with session_factory() as s:
            store_id = str(s.scalars(select(Store.id).where(Store.is_demo.is_(True))).first())
            return BatchIntakeService(s).scan_package(data, store_id=store_id)

    return scanner


def test_real_usb_intake_end_to_end(tmp_path, session_factory):
    with session_factory() as s:
        seeded = seed_with_session(s)
        assert seeded.get("seeded") is not False
        product = s.scalars(select(Product).where(Product.barcode == AAS_ATTA_BARCODE)).one()
        assert product is not None

    service = MobileIntakeService(
        tmp_path,
        scanner=_real_scanner(session_factory),
        stability_sec=0.1,
        stability_sample_sec=0.02,
        max_wait_sec=5.0,
    )
    service.ensure_dirs()
    service.load_index()

    # 1) photo arrives from the "phone" over USB
    src = service.watcher.intake_dir / "phone-IMG-0001.jpg"
    src.write_bytes(build_demo_intake_bytes())

    # 2) watcher ingests it through the REAL pipeline
    handled = service.scan_now()
    assert handled == 1
    job = service.list_jobs()[0]
    assert job["state"] == JobState.REVIEW_REQUIRED.value, job["error"]
    assert job["error"] is None

    # 3) real barcode + OCR + expiry on the candidate
    c = job["candidate"]
    assert c["barcode"] == AAS_ATTA_BARCODE
    assert c["barcode_read"] is True
    assert c["product_found"] is True
    assert c["product_sku"] == "AAS-ATTA"
    assert c["product_name"] == "Aashirvaad Atta 5kg"
    assert c["batch_number"] == "M25-DEMO-01"
    assert c["expiry_date"] is not None  # real OCR read "EXP: 08/2027"
    assert c["mrp"] == "240.00"
    assert c["labels_found"]  # expiry/manufacturing/batch/mrp read for real
    assert c["warnings"] or c["confidence"] is not None

    # 4) human review determines the batch fields
    quantity = 12
    confirm = {
        "store_id": None,
        "product_id": None,
        "quantity": quantity,
        "batch_number": c["batch_number"],
        "expiry_date": datetime.date.fromisoformat(c["expiry_date"]),
        "expiry_date_precision": c["expiry_date_precision"],
        "mrp": Decimal(c["mrp"]),
    }
    with session_factory() as s:
        store_id = str(s.scalars(select(Store.id).where(Store.is_demo.is_(True))).first())
        product_id = str(s.scalars(select(Product.id).where(Product.barcode == AAS_ATTA_BARCODE)).one())
        confirm["store_id"] = store_id
        confirm["product_id"] = product_id
        batch, movement = BatchIntakeService(s).confirm_receipt(**confirm)

    # 5) confirmation wrote an atomic batch + movement (M17 path unchanged)
    assert movement.quantity_change == quantity
    assert batch.batch_number == "M25-DEMO-01"

    # 6) book-keeping: the reviewed job is marked PROCESSED (no DB mutation here)
    closed = service.close_job(job["job_id"])
    assert closed["state"] == JobState.PROCESSED.value

    # 7) catalog: a second demo product (Amul Milk 1L) resolves identically
    src2 = service.watcher.intake_dir / "phone-IMG-0003.jpg"
    src2.write_bytes(build_demo_intake_bytes("amul"))
    assert service.scan_now() == 1
    job2 = [j for j in service.list_jobs() if j["state"] == JobState.REVIEW_REQUIRED.value]
    assert len(job2) == 1
    c2 = job2[0]["candidate"]
    assert c2["barcode"] == "8901262030003"
    assert c2["product_sku"] == "AMUL-MILK"
    assert c2["product_name"] == "Amul Milk 1L"
    assert c2["batch_number"] == "M25-DEMO-02"
    with session_factory() as s:
        store_id = str(s.scalars(select(Store.id).where(Store.is_demo.is_(True))).first())
        product_id = str(s.scalars(select(Product.id).where(Product.barcode == "8901262030003")).one())
        batch2, movement2 = BatchIntakeService(s).confirm_receipt(
            **{
                "store_id": store_id,
                "product_id": product_id,
                "quantity": 6,
                "batch_number": c2["batch_number"],
                "expiry_date": None,
                "expiry_date_precision": c2["expiry_date_precision"],
                "mrp": Decimal(c2["mrp"]),
            }
        )
    assert movement2.quantity_change == 6
    assert batch2.batch_number == "M25-DEMO-02"
    assert service.close_job(job2[0]["job_id"])["state"] == JobState.PROCESSED.value

    # 8) idempotency: the same bytes copied again must NOT double-receive
    (service.watcher.intake_dir / "phone-IMG-0002.jpg").write_bytes(build_demo_intake_bytes())
    service.scan_now()
    jobs = service.list_jobs()
    dup = [j for j in jobs if j["duplicate_of"]]
    assert len(dup) == 1
    # two review jobs closed + one duplicate; no second reviews created
    assert len(jobs) == 3
    assert len([j for j in jobs if j["state"] == JobState.REVIEW_REQUIRED.value]) == 0
    assert all(j["state"] == JobState.PROCESSED.value for j in jobs)

    service.stop()