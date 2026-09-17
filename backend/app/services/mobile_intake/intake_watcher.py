"""Polling watcher over the intake directory (M25).

Single background thread. It:
  1. lists pushed image files in ``intake/``
  2. waits for each file to STOP GROWING (copy-in-progress must never be read)
  3. validates it (extension / size / decode-ability) and hashes its content
  4. de-duplicates identical bytes (deterministic idempotency)
  5. hands the bytes to the existing M17 scan pipeline (barcode → OCR →
     Expiry-Parser → catalog lookup) as a READ-ONLY candidate
  6. moves the file to ``processed/`` (candidate ready for human review) or
     ``failed/`` (rejected / pipeline error) and records a metadata job.

Nothing here mutates the database and no OCR/expiry result is ever invented.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Optional

from .errors import (
    CorruptImageError,
    FileTooLargeError,
    IntakeJobNotFound,
    MobileIntakeError,
    UnsupportedFileError,
)
from .file_stability import wait_until_stable
from .intake_models import IntakeJob, JobState, JobsStore, iso_now
from .validation import (
    ALLOWED_EXTENSIONS,
    ALLOWED_EXTENSION_LABEL,
    file_size_ok,
    sanitise_filename,
    sha256_bytes,
    validates_as_image,
)

logger = logging.getLogger("storeye.mobile_intake")

# Filenames with this prefix are recognised as demo-generated inputs (M25):
# they are processed through the REAL pipeline, then demo-reset can clean them.
DEMO_INPUT_PREFIX = "storeye-demo-"

# Scanner contract: ``callable(bytes) -> PackageScan`` (M17 pipeline).
Scanner = Callable[[bytes], object]


def snapshot_candidate(scan: object) -> dict:
    """Flatten a ``PackageScan.candidate`` into JSON-safe primitives."""
    from dataclasses import asdict
    from datetime import date, datetime
    from decimal import Decimal

    candidate = getattr(scan, "candidate", {})
    if hasattr(candidate, "to_dict"):
        data = candidate.to_dict()
    else:
        data = asdict(candidate) if not isinstance(candidate, dict) else dict(candidate)

    def _conv(value):
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        return value

    return {
        key: [_conv(item) for item in value] if isinstance(value, list) else _conv(value)
        for key, value in data.items()
    }


def _move(path: Path, target: Path) -> None:
    try:
        path.replace(target)
    except OSError as exc:
        if exc.errno != 18:  # EXDEV — cross-filesystem (e.g. mounted phone)
            raise
        shutil.move(str(path), str(target))


class IntakeFileWatcher:
    """Polling watcher for phone-pushed images under ``<root>/intake``."""

    def __init__(
        self,
        root,
        *,
        store: JobsStore,
        scanner: Scanner,
        watch_interval_sec: float = 1.0,
        stability_sec: float = 2.0,
        stability_sample_sec: float = 0.25,
        max_wait_sec: float = 60.0,
        max_file_bytes: Optional[int] = None,
        retention_days: int = 7,
        sleep_fn=time.sleep,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.root = Path(root)
        self.store = store
        self.scanner = scanner
        self.watch_interval_sec = watch_interval_sec
        self.stability_sec = stability_sec
        self.stability_sample_sec = stability_sample_sec
        self.max_wait_sec = max_wait_sec
        self.max_file_bytes = max_file_bytes
        self.retention_days = retention_days
        self._sleep = sleep_fn
        self.log = logger or logging.getLogger(__name__)

        self.intake_dir = self.root / "intake"
        self.processing_dir = self.root / "processing"
        self.processed_dir = self.root / "processed"
        self.failed_dir = self.root / "failed"

        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._tick_lock = threading.Lock()
        self.last_scan_at: Optional[str] = None
        self.scans = 0
        self.duplicates = 0
        self.rejected = 0

    # -- lifecycle ----------------------------------------------------------
    def ensure_dirs(self) -> None:
        for d in (self.intake_dir, self.processing_dir, self.processed_dir, self.failed_dir):
            d.mkdir(parents=True, exist_ok=True)

    def start(self) -> bool:
        if self.is_alive():
            return False
        self.ensure_dirs()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="storeye-mobile-intake-watcher", daemon=True
        )
        self._thread.start()
        return True

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._thread = None

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- loop ---------------------------------------------------------------
    def _run_loop(self) -> None:
        while not self._stop.is_set():
            self.scan_dir_once()
            self._sleep(self.watch_interval_sec)

    def scan_dir_once(self) -> int:
        """Process every pushed file currently sitting in ``intake/``.

        Returns the number of files ingested (or attempted) this tick.
        """
        with self._tick_lock:
            self.last_scan_at = iso_now()
            try:
                entries = [
                    p
                    for p in os.scandir(self.intake_dir)
                    if p.is_file() and not p.name.startswith(".")
                ]
            except OSError:
                return 0
            entries.sort(key=lambda e: (e.stat(follow_symlinks=False).st_mtime, e.name))
            handled = 0
            for entry in entries:
                if self._stop.is_set():
                    break
                self._ingest(Path(entry.path))
                handled += 1
            self._cleanup_retention()
            return handled

    # -- ingest -------------------------------------------------------------
    def _ingest(self, src: Path) -> None:
        src = src.resolve()
        try:
            safe = sanitise_filename(src.name)
        except ValueError as exc:
            self._reject(src, f"Invalid file name rejected: {exc}", "BAD_FILENAME")
            return

        now = iso_now()
        job = IntakeJob(
            job_id=uuid.uuid4().hex[:12],
            hash="",
            filename=safe,
            stored_path="",
            size=0,
            state=JobState.DETECTED,
            created_at=now,
            updated_at=now,
            demo=safe.startswith(DEMO_INPUT_PREFIX),
        )
        self.store.upsert(job)

        job.state = JobState.WAITING_FOR_COPY
        self._touch(job)

        if not wait_until_stable(
            src,
            interval=max(0.05, self.stability_sample_sec),
            stability_sec=self.stability_sec,
            max_wait_sec=self.max_wait_sec,
            sleep_fn=self._sleep,
        ):
            self._fail_existing(
                job,
                src,
                "File never stopped growing: the copy did not complete within the wait window.",
                "COPY_NOT_FINISHED",
            )
            return

        job.state = JobState.PROCESSING
        self._touch(job)

        try:
            ext = os.path.splitext(safe)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                raise UnsupportedFileError(
                    f"Unsupported file type '{ext or 'none'}'. Allowed: {ALLOWED_EXTENSION_LABEL}."
                )
            size = src.stat().st_size
            if not file_size_ok(size, self.max_file_bytes):
                limit = self.max_file_bytes or 0
                raise FileTooLargeError(
                    f"File is {size} bytes; the intake limit is {limit} bytes. Skip it or shrink it."
                )
            data = src.read_bytes()
            if not validates_as_image(data):
                raise CorruptImageError("File cannot be decoded as an image (corrupt or partial).")

            digest = sha256_bytes(data)
            job.size = size

            existing = self.store.get_by_hash(digest)
            if existing is not None and existing.job_id != job.job_id:
                self.duplicates += 1
                if existing.state is JobState.FAILED:
                    self._fail_existing(
                        job,
                        src,
                        f"Duplicate of failed job '{existing.job_id}'; not reprocessed automatically. "
                        "Use the rescan API after fixing the source image.",
                        "DUPLICATE_OF_FAILED",
                        duplicate_of=existing.job_id,
                    )
                else:
                    job.hash = digest
                    job.state = JobState.PROCESSED
                    job.duplicate_of = existing.job_id
                    job.note = (
                        f"Identical to job '{existing.job_id}' — recognised as a duplicate, "
                        "not received twice."
                    )
                    dst = self._store_file(job, src, self.processed_dir)
                    self._touch(job, stored=job.stored_path)
                return

            job.hash = digest
            dst = self._store_file(job, src, self.processing_dir)
            job.state = JobState.SCANNING
            self._touch(job)

            try:
                scan = self.scanner(dst.read_bytes())
            except Exception as exc:  # scan pipeline failure -> FAILED
                self.log.exception("scan pipeline failed for %s", job.job_id)
                self._fail_existing(
                    job,
                    dst,
                    f"Scan pipeline error: {exc}",
                    "SCAN_FAILED",
                    target_dir=self.failed_dir,
                )
                return

            job.state = JobState.OCR_PROCESSING
            job.candidate = snapshot_candidate(scan)
            job.acceptable = bool(getattr(scan, "acceptable", True))
            job.reason = str(getattr(scan, "reason", ""))
            job.state = JobState.REVIEW_REQUIRED
            job.error = None
            self.scans += 1
            dst2 = self._store_file(job, dst, self.processed_dir, force_rename=True)
            self._touch(job, stored=job.stored_path)
            self.log.info(
                "mobile intake job %s ready for review (acceptable=%s)", job.job_id, job.acceptable
            )
        except (UnsupportedFileError, FileTooLargeError, CorruptImageError) as exc:
            self.rejected += 1
            self._fail_existing(job, src, str(exc), exc.code)

    # -- helpers ------------------------------------------------------------
    def _store_file(self, job: IntakeJob, src: Path, target_dir: Path, *, force_rename: bool = False) -> Path:
        filename = f"{job.job_id}__{job.filename}"
        dst = target_dir / filename
        if src.parent != dst.parent or force_rename:
            _move(src, dst)
        job.stored_path = f"{target_dir.name}/{filename}"
        return dst

    def _touch(self, job: IntakeJob, *, stored: Optional[str] = None) -> None:
        job.updated_at = iso_now()
        if stored is not None:
            job.stored_path = stored
        self.store.upsert(job)

    def _fail_existing(
        self,
        job: IntakeJob,
        src: Path,
        message: str,
        code: str,
        *,
        duplicate_of: Optional[str] = None,
        target_dir: Optional[Path] = None,
    ) -> None:
        job.state = JobState.FAILED
        job.error = f"[{code}] {message}"
        job.duplicate_of = duplicate_of or job.duplicate_of
        dst = self._store_file(job, src, target_dir or self.failed_dir)
        self._touch(job, stored=job.stored_path)
        self.log.warning("mobile intake job %s failed: %s", job.job_id, job.error)

    def _reject(self, src: Path, message: str, code: str) -> None:
        """A file so malformed it pre-dates job creation — move it to failed/."""
        with self._tick_lock:
            self.rejected += 1
            now = iso_now()
            job = IntakeJob(
                job_id=uuid.uuid4().hex[:12],
                hash="",
                filename=src.name or "file",
                stored_path="",
                size=0,
                state=JobState.FAILED,
                created_at=now,
                updated_at=now,
                demo=src.name.startswith(DEMO_INPUT_PREFIX),
                error=f"[{code}] {message}",
            )
            dst = self._store_file(job, src, self.failed_dir)
            job.stored_path = f"{self.failed_dir.name}/{dst.name}"
            self._touch(job)
            self.log.warning("mobile intake rejected file %s: %s", src.name, message)

    # -- retention ----------------------------------------------------------
    def _cleanup_retention(self) -> None:
        if self.retention_days <= 0:
            return
        from datetime import datetime, timezone, timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        jobs = self.store.all()
        active = {j.job_id for j in jobs if j.state not in {JobState.PROCESSED, JobState.FAILED}}
        removed_files = 0
        for folder in (self.processed_dir, self.failed_dir):
            try:
                candidates = [p for p in folder.iterdir() if p.is_file()]
            except OSError:
                continue
            for p in candidates:
                job_id = p.name.split("__", 1)[0]
                if job_id in active:
                    continue
                try:
                    if datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc) < cutoff:
                        p.unlink()
                        removed_files += 1
                except OSError:
                    continue
        # Prune terminal index rows older than the cutoff.
        for j in list(jobs):
            if j.state in {JobState.PROCESSED, JobState.FAILED}:
                try:
                    parsed = datetime.fromisoformat(j.updated_at)
                    if parsed < cutoff:
                        self.store.delete(j.job_id)
                except ValueError:
                    continue
        if removed_files:
            self.store.save()