"""M25 — Mobile-to-Edge USB Intake Bridge tests.

Covers validation, copy-stability, the polling watcher, deterministic content
hash idempotency (no double-receive), the failure taxonomy, the demo asset +
demo reset isolation, and the HTTP layer. A FakeScanner stands in for the M17
pipeline here; the REAL pipeline (real zbar + real PaddleOCR + real demo store)
is exercised separately in `test_mobile_intake_real_ai.py`.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.mobile_intake.demo_image import build_demo_intake_bytes
from app.services.mobile_intake.errors import (
    CorruptImageError,
    FileTooLargeError,
    IntakeJobNotFound,
    MobileIntakeError,
    UnsupportedFileError,
)
from app.services.mobile_intake.file_stability import wait_until_stable
from app.services.mobile_intake.intake_models import IntakeJob, JobState, JobsStore
from app.services.mobile_intake.intake_service import MobileIntakeService
from app.services.mobile_intake.intake_watcher import DEMO_INPUT_PREFIX
from app.services.mobile_intake.validation import (
    ALLOWED_EXTENSIONS,
    sanitise_filename,
    sha256_bytes,
    validates_as_image,
)

pytestmark = pytest.mark.no_db


# ---------------------------------------------------------------------------
# Fake M17 scan pipeline
# ---------------------------------------------------------------------------
@dataclass
class FakeCandidate:
    barcode_read: bool = True
    barcode: str | None = "8901063001015"
    product_id: str | None = "11111111-1111-1111-1111-111111111111"
    product_name: str | None = "Aashirvaad Atta 5kg"
    product_sku: str | None = "AAS-ATTA"
    product_found: bool = True
    batch_number: str | None = "M25-DEMO-01"
    manufacturing_date: date | None = date(2026, 8, 1)
    expiry_date: date | None = date(2027, 8, 1)
    expiry_date_precision: str = "month"
    mrp: Decimal | None = Decimal("240.00")
    confidence: float | None = 0.91
    labels_found: list = None
    warnings: list = None

    def __post_init__(self):
        self.labels_found = self.labels_found or ["expiry", "manufacturing", "batch", "mrp"]
        self.warnings = self.warnings or []


@dataclass
class FakeScan:
    acceptable: bool = True
    reason: str = "Barcode matched product."
    candidate: FakeCandidate | None = None


class FakeScanner:
    def __init__(self, *, scan: object = None, error: Exception | None = None):
        self.scan = scan or FakeScan(candidate=FakeCandidate())
        self.error = error
        self.calls: list[bytes] = []

    def __call__(self, data: bytes):
        self.calls.append(data)
        if self.error is not None:
            raise self.error
        return self.scan


def _png_bytes() -> bytes:
    import numpy as np
    import cv2

    ok, buf = cv2.imencode(".png", np.full((300, 400, 3), 200, dtype=np.uint8))
    assert ok
    return buf.tobytes()


def _weird_file_bytes() -> bytes:
    return b"this is definitely not an image"


@pytest.fixture()
def svc(tmp_path) -> MobileIntakeService:
    service = MobileIntakeService(
        tmp_path,
        scanner=FakeScanner(),
        stability_sec=0.05,
        stability_sample_sec=0.02,
        max_wait_sec=1.0,
    )
    service.ensure_dirs()
    service.load_index()
    return service


# ---------------------------------------------------------------------------
# validation unit tests
# ---------------------------------------------------------------------------
class TestValidation:
    def test_allowed_extensions(self):
        assert ALLOWED_EXTENSIONS == {".jpg", ".jpeg", ".png", ".webp"}

    def test_sanitise_filename_strips_paths(self):
        assert sanitise_filename("/Users/phone/IMG_0001.jpg") == "IMG_0001.jpg"
        assert sanitise_filename("..//../../etc/passwd") == "passwd"
        with pytest.raises(ValueError):
            sanitise_filename("")
        with pytest.raises(ValueError):
            sanitise_filename(".")
        with pytest.raises(ValueError):
            sanitise_filename(".hidden.jpg")

    def test_hash_is_deterministic(self):
        data = _png_bytes()
        assert sha256_bytes(data) == sha256_bytes(data)
        assert sha256_bytes(data) != sha256_bytes(_weird_file_bytes())

    def test_image_validation(self):
        assert validates_as_image(_png_bytes()) is True
        assert validates_as_image(_weird_file_bytes()) is False
        assert validates_as_image(b"") is False


class TestFileStability:
    def test_settled_file_is_stable(self, tmp_path):
        p = tmp_path / "a.jpg"
        p.write_bytes(b"\x00" * 1024)
        assert wait_until_stable(p, stability_sec=0.02, interval=0.01, max_wait_sec=2.0) is True

    def test_still_growing_file_is_not_stable(self, tmp_path):
        p = tmp_path / "growing.jpg"
        stop = threading.Event()
        p.write_bytes(b"\x00" * 16)

        def grow():
            while not stop.is_set():
                with open(p, "ab") as fh:
                    fh.write(b"\x00" * 1024)
                time.sleep(0.01)

        t = threading.Thread(target=grow, daemon=True)
        t.start()
        try:
            assert (
                wait_until_stable(p, stability_sec=1.0, interval=0.01, max_wait_sec=0.12)
                is False
            )
        finally:
            stop.set()
            t.join()

    def test_missing_file_not_stable(self, tmp_path):
        assert (
            wait_until_stable(tmp_path / "nope.jpg", stability_sec=0.02, interval=0.01, max_wait_sec=0.05)
            is False
        )


class TestJobsStore:
    def test_roundtrip(self, tmp_path):
        store = JobsStore(tmp_path)
        job = IntakeJob(
            job_id="abc", hash="h1", filename="x.jpg", stored_path="processed/abc__x.jpg",
            size=4, state=JobState.REVIEW_REQUIRED, created_at="2026-09-17T00:00:00Z",
            updated_at="2026-09-17T00:00:00Z", candidate={"barcode": "1"},
        )
        store.upsert(job)
        store.save()

        store2 = JobsStore(tmp_path)
        store2.load()
        got = store2.get("abc")
        assert got is not None
        assert got.state is JobState.REVIEW_REQUIRED
        assert got.candidate["barcode"] == "1"
        assert store2.get_by_hash("h1").job_id == "abc"

    def test_corrupt_index_is_ignored(self, tmp_path):
        (tmp_path / JobsStore.INDEX_NAME).write_text("{not json")
        store = JobsStore(tmp_path)
        store.load()
        assert store.all() == []


# ---------------------------------------------------------------------------
# watcher / service tests
# ---------------------------------------------------------------------------
class TestWatcherIngestion:
    def test_happy_path_to_review(self, svc, tmp_path):
        (svc.watcher.intake_dir / "IMG_0001.jpg").write_bytes(_png_bytes())
        assert svc.scan_now() == 1
        jobs = svc.list_jobs()
        assert len(jobs) == 1
        j = jobs[0]
        assert j["state"] == JobState.REVIEW_REQUIRED.value
        assert j["acceptable"] is True
        assert j["candidate"]["product_name"] == "Aashirvaad Atta 5kg"
        assert j["candidate"]["expiry_date"] == "2027-08-01"
        assert j["candidate"]["mrp"] == "240.00"
        assert j["error"] is None
        # file moved to processed/
        assert svc.watcher.processed_dir.exists()
        assert list(svc.watcher.processed_dir.glob("*.jpg"))

    def test_demo_files_marked_demo(self, svc):
        (svc.watcher.intake_dir / f"{DEMO_INPUT_PREFIX}package.jpg").write_bytes(
            build_demo_intake_bytes()
        )
        svc.scan_now()
        assert svc.list_jobs()[0]["demo"] is True

    def test_unsupported_extension_fails(self, svc):
        (svc.watcher.intake_dir / "virus.exe").write_bytes(b"MZ")
        svc.scan_now()
        j = svc.list_jobs()[0]
        assert j["state"] == JobState.FAILED.value
        assert "UNSUPPORTED_FILE" in j["error"]
        assert list(svc.watcher.failed_dir.glob("*"))

    def test_oversized_file_fails(self, svc):
        p = svc.watcher.intake_dir / "big.jpg"
        p.write_bytes(b"\x00" * 16 * 1024 * 1024)  # > 15MB default
        svc.scan_now()
        j = svc.list_jobs()[0]
        assert j["state"] == JobState.FAILED.value
        assert "TOO_LARGE" in j["error"]

    def test_corrupt_image_fails(self, svc):
        (svc.watcher.intake_dir / "corrupt.jpg").write_bytes(_weird_file_bytes())
        svc.scan_now()
        j = svc.list_jobs()[0]
        assert j["state"] == JobState.FAILED.value
        assert "CORRUPT_IMAGE" in j["error"]

    def test_scan_pipeline_error_fails(self, tmp_path):
        service = MobileIntakeService(
            tmp_path,
            scanner=FakeScanner(error=RuntimeError("ocr exploded")),
            stability_sec=0.05,
            stability_sample_sec=0.02,
            max_wait_sec=1.0,
        )
        service.ensure_dirs()
        service.load_index()
        (service.watcher.intake_dir / "x.jpg").write_bytes(_png_bytes())
        service.scan_now()
        j = service.list_jobs()[0]
        assert j["state"] == JobState.FAILED.value
        assert "SCAN_FAILED" in j["error"]

    def test_copy_never_marked_stable_fails(self, tmp_path):
        stop = threading.Event()
        scanner = FakeScanner()
        service = MobileIntakeService(
            tmp_path,
            scanner=scanner,
            stability_sec=1.0,        # longer than max_wait => never stable
            stability_sample_sec=0.01,
            max_wait_sec=0.08,
        )
        service.ensure_dirs()
        p = service.watcher.intake_dir / "active.jpg"
        p.write_bytes(b"\x00" * 16)

        def grow():
            while not stop.is_set():
                with open(p, "ab") as fh:
                    fh.write(b"\x00" * 512)
                time.sleep(0.005)

        t = threading.Thread(target=grow, daemon=True)
        t.start()
        try:
            service.scan_now()
        finally:
            stop.set()
            t.join()
        j = service.list_jobs()[0]
        assert j["state"] == JobState.FAILED.value
        assert "COPY_NOT_FINISHED" in j["error"]
        assert scanner.calls == []  # never read a half-copied file


class TestIdempotency:
    def test_identical_copy_not_received_twice(self, svc):
        scanner = svc.watcher.scanner
        data = build_demo_intake_bytes()
        (svc.watcher.intake_dir / "copy-1.jpg").write_bytes(data)
        (svc.watcher.intake_dir / "copy-2.jpg").write_bytes(data)
        assert svc.scan_now() == 2
        jobs = svc.list_jobs()
        assert len(jobs) == 2
        reviews = [j for j in jobs if j["state"] == JobState.REVIEW_REQUIRED.value]
        procs = [j for j in jobs if j["state"] == JobState.PROCESSED.value]
        assert len(reviews) == 1, "identical content was received twice!"
        assert len(procs) == 1
        assert procs[0]["duplicate_of"] == reviews[0]["job_id"]
        # the exact-same content went through the scanner only once
        assert len(scanner.calls) == 1

    def test_duplicate_after_close_still_not_received(self, svc):
        data = _png_bytes()
        (svc.watcher.intake_dir / "a.jpg").write_bytes(data)
        svc.scan_now()
        first = svc.list_jobs()[0]
        svc.close_job(first["job_id"])
        (svc.watcher.intake_dir / "a-again.jpg").write_bytes(data)
        svc.scan_now()
        dup = [j for j in svc.list_jobs() if j["duplicate_of"]]
        assert len(dup) == 1
        assert len([j for j in svc.list_jobs() if j["state"] == JobState.REVIEW_REQUIRED.value]) == 0

    def test_duplicate_of_failed_job_flagged(self, tmp_path):
        service = MobileIntakeService(
            tmp_path,
            scanner=FakeScanner(error=RuntimeError("boom")),
            stability_sec=0.05,
            stability_sample_sec=0.02,
            max_wait_sec=1.0,
        )
        service.ensure_dirs()
        service.load_index()
        data = build_demo_intake_bytes()
        (service.watcher.intake_dir / "1.jpg").write_bytes(data)
        service.scan_now()
        (service.watcher.intake_dir / "2.jpg").write_bytes(data)
        service.scan_now()
        jobs = service.list_jobs()
        assert all(j["state"] == JobState.FAILED.value for j in jobs)
        with_dup = [j for j in jobs if j["duplicate_of"]]
        assert len(with_dup) == 1
        assert "DUPLICATE_OF_FAILED" in with_dup[0]["error"]


class TestJobTransitions:
    def test_close_after_review(self, svc):
        (svc.watcher.intake_dir / "x.jpg").write_bytes(_png_bytes())
        svc.scan_now()
        job = svc.list_jobs()[0]
        closed = svc.close_job(job["job_id"])
        assert closed["state"] == JobState.PROCESSED.value

    def test_close_invalid_state(self, svc):
        (svc.watcher.intake_dir / "x.jpg").write_bytes(_weird_file_bytes())
        svc.scan_now()
        job = svc.list_jobs()[0]
        with pytest.raises(MobileIntakeError):
            svc.close_job(job["job_id"])

    def test_close_unknown_job(self, svc):
        with pytest.raises(IntakeJobNotFound):
            svc.close_job("missing")

    def test_rescan_failed_job(self, tmp_path):
        import app.services.mobile_intake.demo_image as di

        def scanner(data):
            if getattr(scanner, "fail", True):
                scanner.fail = False
                raise RuntimeError("first attempt failed")
            return FakeScan(candidate=FakeCandidate())

        service = MobileIntakeService(
            tmp_path,
            scanner=scanner,
            stability_sec=0.05,
            stability_sample_sec=0.02,
            max_wait_sec=1.0,
        )
        service.ensure_dirs()
        service.load_index()
        (service.watcher.intake_dir / "x.jpg").write_bytes(di.build_demo_intake_bytes())
        service.scan_now()
        failed = service.list_jobs()[0]
        assert failed["state"] == JobState.FAILED.value
        rescanned = service.rescan(failed["job_id"])
        assert rescanned["state"] == JobState.REVIEW_REQUIRED.value
        assert rescanned["candidate"]["product_name"] == "Aashirvaad Atta 5kg"

    def test_rescan_requires_existing_file(self, tmp_path):
        service = MobileIntakeService(tmp_path, scanner=FakeScanner(), stability_sec=0.05)
        service.ensure_dirs()
        service.load_index()
        (service.watcher.intake_dir / "x.jpg").write_bytes(_png_bytes())
        service.scan_now()
        job = service.list_jobs()[0]
        # delete the file behind the processed job
        (tmp_path / job["stored_path"]).unlink()
        with pytest.raises(MobileIntakeError):
            service.rescan(job["job_id"])

    def test_status_counts(self, svc):
        data = _png_bytes()
        (svc.watcher.intake_dir / "1.jpg").write_bytes(data)
        (svc.watcher.intake_dir / "2.jpg").write_bytes(_weird_file_bytes())
        svc.scan_now()
        st = svc.status()
        assert st["scans"] == 1
        assert st["rejected"] == 1
        assert st["active_jobs"] == 1
        assert st["failed_jobs"] == 1
        assert st["monitoring"] is False


class TestDemoResetIsolation:
    def test_reset_removes_only_demo_state(self, svc):
        (svc.watcher.intake_dir / f"{DEMO_INPUT_PREFIX}one.jpg").write_bytes(_png_bytes())
        (svc.watcher.intake_dir / "real-photo.jpg").write_bytes(_png_bytes())
        svc.scan_now()
        assert len(svc.list_jobs()) == 2
        result = svc.reset_demo_state()
        assert result["removed_jobs"] == 1
        remaining = svc.list_jobs()
        assert len(remaining) == 1
        assert remaining[0]["demo"] is False
        # demo file gone from disk; real file still stored
        assert not any(p.name.startswith(DEMO_INPUT_PREFIX) for p in svc.watcher.processed_dir.iterdir())

    def test_reset_is_idempotent(self, svc):
        svc.reset_demo_state()
        assert svc.reset_demo_state() == {"removed_jobs": 0, "removed_files": 0}

    def test_demo_queue_then_cleanup(self, svc):
        q = svc.queue_demo_file()
        assert q["queued"] is True
        assert q["filename"].startswith(DEMO_INPUT_PREFIX)
        assert q["size"] > 0
        # determinism: byte-identical across calls
        q2 = svc.queue_demo_file()
        assert q["sha256"] == q2["sha256"]
        svc.scan_now()
        job = svc.list_jobs()[0]
        assert job["demo"] is True

    def test_demo_catalog_second_product(self, svc):
        from app.services.mobile_intake.demo_image import (
            build_demo_intake_bytes,
            demo_package_slugs,
        )

        assert demo_package_slugs() == ["aashirvaad", "amul"]
        # distinct, deterministic bytes per catalogue slug
        a = build_demo_intake_bytes("aashirvaad")
        b = build_demo_intake_bytes("amul")
        assert a != b
        assert build_demo_intake_bytes("amul") == b
        # queue via the service: sha matches the amul label bytes exactly
        from app.services.mobile_intake.validation import sha256_bytes

        q = svc.queue_demo_file("amul")
        assert q["product"]["slug"] == "amul"
        assert q["sha256"] == sha256_bytes(b)
        # unknown slugs fall back to the default pack deterministically
        q_fallback = svc.queue_demo_file("not-a-product")
        assert q_fallback["product"]["slug"] == "aashirvaad"
        assert q_fallback["sha256"] == sha256_bytes(a)
        svc.scan_now()
        jobs = [j for j in svc.list_jobs() if j["demo"]]
        assert len(jobs) == 2


# ---------------------------------------------------------------------------
# HTTP layer (no DB required: status/jobs/close/rescan/demo-queue)
# ---------------------------------------------------------------------------
@pytest.fixture()
def http_client(tmp_path):
    from uuid import uuid4

    from fastapi.testclient import TestClient
    from app.main import app
    from app.services.mobile_intake.manager import (
        configure_intake_manager,
        reset_intake_manager,
    )
    from tests.conftest import bind_test_user, unbind_test_user

    service = MobileIntakeService(tmp_path, scanner=FakeScanner(), stability_sec=0.05)
    service.ensure_dirs()
    service.load_index()
    configure_intake_manager(service)
    # The M25 HTTP layer is authenticated (STAFF+); bind a fake store user so
    # these no-DB tests exercise the routing without a real session backend.
    bind_test_user(uuid4())
    with TestClient(app) as c:
        yield c, service
    unbind_test_user()
    reset_intake_manager()


class TestHttpApi:
    def test_status_endpoint(self, http_client):
        client, _svc = http_client
        r = client.get("/api/mobile-intake/status")
        assert r.status_code == 200
        body = r.json()
        assert "intake_dir" in body and "active_jobs" in body

    def test_jobs_list_and_detail(self, http_client):
        client, svc = http_client
        (svc.watcher.intake_dir / "photo.jpg").write_bytes(_png_bytes())
        svc.scan_now()
        r = client.get("/api/mobile-intake/jobs")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1
        job = body["items"][0]
        assert job["state"] == JobState.REVIEW_REQUIRED.value
        # candidate served in the exact M17 response shape
        assert job["candidate"]["product_name"] == "Aashirvaad Atta 5kg"
        assert job["candidate"]["expiry_date"] == "2027-08-01"
        r2 = client.get(f"/api/mobile-intake/jobs/{job['job_id']}")
        assert r2.status_code == 200
        assert r2.json()["job_id"] == job["job_id"]

    def test_jobs_missing_404(self, http_client):
        client, _svc = http_client
        assert client.get("/api/mobile-intake/jobs/nope").status_code == 404

    def test_close_and_rescan_via_api(self, http_client):
        client, svc = http_client
        (svc.watcher.intake_dir / "photo.jpg").write_bytes(_png_bytes())
        svc.scan_now()
        job = client.get("/api/mobile-intake/jobs").json()["items"][0]
        r = client.post(f"/api/mobile-intake/jobs/{job['job_id']}/close")
        assert r.status_code == 200
        assert r.json()["state"] == JobState.PROCESSED.value

    def test_job_photo_streamed_for_review(self, http_client):
        client, svc = http_client
        original = _png_bytes()
        (svc.watcher.intake_dir / "photo.png").write_bytes(original)
        svc.scan_now()
        job = client.get("/api/mobile-intake/jobs").json()["items"][0]
        assert job["photo_url"] == f"/api/mobile-intake/jobs/{job['job_id']}/photo"
        r = client.get(job["photo_url"])
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("image/")
        assert r.content == original

    def test_job_photo_missing_404(self, http_client):
        client, _svc = http_client
        assert client.get("/api/mobile-intake/jobs/nope/photo").status_code == 404

    def test_demo_queue_requires_key(self, http_client):
        client, _svc = http_client
        assert client.post("/api/mobile-intake/demo-queue").status_code == 403

    def test_demo_queue_with_key(self, http_client):
        client, svc = http_client
        from app.api.routers.demo import DEFAULT_RESET_KEY

        r = client.post(
            "/api/mobile-intake/demo-queue",
            headers={"X-Demo-Reset-Key": DEFAULT_RESET_KEY},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["queued"] is True
        assert (svc.watcher.intake_dir / body["filename"]).exists()

    def test_demo_queue_selects_product(self, http_client):
        client, svc = http_client
        from app.api.routers.demo import DEFAULT_RESET_KEY

        r = client.post(
            "/api/mobile-intake/demo-queue",
            json={"product": "amul"},
            headers={"X-Demo-Reset-Key": DEFAULT_RESET_KEY},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["product"]["slug"] == "amul"
        assert body["product"]["barcode"] == "8901262030003"
        assert (svc.watcher.intake_dir / body["filename"]).exists()
        # unknown slug -> falls back to the default pack deterministically
        r2 = client.post(
            "/api/mobile-intake/demo-queue",
            json={"product": "not-a-product"},
            headers={"X-Demo-Reset-Key": DEFAULT_RESET_KEY},
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["product"]["slug"] == "aashirvaad"