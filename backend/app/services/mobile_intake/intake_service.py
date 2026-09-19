"""MobileIntakeService — the API-facing orchestrator (M25).

Owns the intake root, the JSON job index and the polling watcher. All database
writes remain where they already belong: the M17 confirmation flow
(`POST /api/batch-intake/confirm`) — this service NEVER mutates inventory.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable, Optional

from .errors import IntakeDuplicateError, IntakeJobNotFound, MobileIntakeError
from .intake_models import IntakeJob, JobState, JobsStore, iso_now
from .intake_watcher import (
    DEMO_INPUT_PREFIX,
    IntakeFileWatcher,
    Scanner,
    _move,
    snapshot_candidate,
    wait_until_stable,
)
from .validation import sha256_bytes

APPROVABLE = {JobState.REVIEW_REQUIRED, JobState.CONFIRMED}


class MobileIntakeService:
    """Bridge over the intake directory: it exposes status, jobs, rescan,
    demo-queue and demo-reset operations to the HTTP layer and to tests."""

    def __init__(
        self,
        root,
        *,
        scanner: Optional[Scanner] = None,
        watch_interval_sec: float = 1.0,
        stability_sec: float = 2.0,
        stability_sample_sec: float = 0.25,
        max_wait_sec: float = 60.0,
        max_file_bytes: Optional[int] = None,
        retention_days: int = 7,
        sleep_fn=__import__("time").sleep,
        auto_start: bool = False,
    ) -> None:
        self.root = Path(root)
        self.store = JobsStore(self.root)
        self.watcher: IntakeFileWatcher = IntakeFileWatcher(
            self.root,
            store=self.store,
            scanner=scanner or self._noop_scanner,
            watch_interval_sec=watch_interval_sec,
            stability_sec=stability_sec,
            stability_sample_sec=stability_sample_sec,
            max_wait_sec=max_wait_sec,
            max_file_bytes=max_file_bytes,
            retention_days=retention_days,
            sleep_fn=sleep_fn,
        )
        self.monitoring = False
        self.started_at: Optional[str] = None

    @staticmethod
    def _noop_scanner(data: bytes) -> object:
        raise MobileIntakeError("No scan pipeline configured for this intake service.")

    # -- lifecycle ----------------------------------------------------------
    def ensure_dirs(self) -> None:
        self.watcher.ensure_dirs()

    def load_index(self) -> None:
        self.store.load()

    def start(self) -> bool:
        self.ensure_dirs()
        self.load_index()
        started = self.watcher.start()
        self.monitoring = started or self.monitoring
        self.started_at = iso_now()
        return started

    def stop(self, timeout: float = 5.0) -> None:
        self.watcher.stop(timeout=timeout)
        self.monitoring = False

    def scan_now(self) -> int:
        self.ensure_dirs()
        return self.watcher.scan_dir_once()

    # -- queries ------------------------------------------------------------
    def status(self) -> dict:
        jobs = self.store.all()
        active = sum(1 for j in jobs if j.state not in {JobState.PROCESSED, JobState.FAILED})
        failed = sum(1 for j in jobs if j.state == JobState.FAILED)
        return {
            "monitoring": self.monitoring,
            "watcher_alive": self.watcher.is_alive(),
            "intake_dir": str(self.watcher.intake_dir),
            "processing_dir": str(self.watcher.processing_dir),
            "processed_dir": str(self.watcher.processed_dir),
            "failed_dir": str(self.watcher.failed_dir),
            "watched_at": self.watcher.last_scan_at,
            "started_at": self.started_at,
            "scans": self.watcher.scans,
            "duplicates": self.watcher.duplicates,
            "rejected": self.watcher.rejected,
            "active_jobs": active,
            "failed_jobs": failed,
        }

    def list_jobs(self) -> list[dict]:
        return [j.to_dict() for j in self.store.all()]

    def get_job(self, job_id: str) -> dict:
        job = self.store.get(job_id)
        if job is None:
            raise IntakeJobNotFound(f"No mobile intake job '{job_id}'.")
        return job.to_dict()

    def photo_path(self, job_id: str) -> Path:
        """Resolve the on-disk photo for a job (served to the review screen).

        The photo never enters PostgreSQL (M22); it is streamed from the intake
        root. The resolved path is constrained to the root so a crafted
        `stored_path` can never read an arbitrary file.
        """
        job = self._require(job_id)
        if not job.stored_path:
            raise MobileIntakeError(f"Job '{job_id}' has no stored photo.")
        root = self.root.resolve()
        candidate = (root / job.stored_path).resolve()
        if candidate != root and root not in candidate.parents:
            raise MobileIntakeError(
                f"Job '{job_id}' photo path escapes the intake root."
            )
        if not candidate.is_file():
            raise MobileIntakeError(
                f"Photo for job '{job_id}' is no longer on disk."
            )
        return candidate

    # -- human-driven transitions -------------------------------------------
    def close_job(self, job_id: str) -> dict:
        """Book-keeping only: mark a reviewed candidate as fully processed.

        Invoked AFTER the human completed the real M17 confirmation (the only
        path that writes batches/inventory). No database mutation here.
        """
        job = self._require(job_id)
        if job.state not in APPROVABLE:
            raise MobileIntakeError(
                f"Job '{job_id}' is in state {job.state.value}; only "
                f"{', '.join(s.value for s in sorted(APPROVABLE, key=lambda x: x.value))} can be closed."
            )
        job.state = JobState.PROCESSED
        job.note = "Confirmed by the shopkeeper via the Smart Batch Intake flow."
        job.updated_at = iso_now()
        self.store.upsert(job)
        return job.to_dict()

    def rescan(self, job_id: str) -> dict:
        """Re-run the real scan pipeline over a FAILED/REVIEW job's photo.

        Refuses to process jobs that were rejected at validation (the bytes
        are corrupt); only scan-stage outcomes can be retried. The new
        candidate replaces the old one; no DB writes happen here either.
        """
        job = self._require(job_id)
        if job.state not in {JobState.FAILED, JobState.REVIEW_REQUIRED}:
            raise MobileIntakeError(
                f"Job '{job_id}' is in state {job.state.value}; only FAILED or REVIEW_REQUIRED jobs can be rescanned."
            )
        path = self.root / job.stored_path if job.stored_path else None
        if path is None or not path.is_file():
            raise MobileIntakeError(
                f"Source file for job '{job_id}' is no longer available on disk; rescan impossible."
            )

        job.state = JobState.SCANNING
        job.error = None
        job.updated_at = iso_now()
        self.store.upsert(job)
        try:
            scan = self.watcher.scanner(path.read_bytes())
            job.candidate = snapshot_candidate(scan)
            job.acceptable = bool(getattr(scan, "acceptable", True))
            job.reason = str(getattr(scan, "reason", ""))
            job.state = JobState.REVIEW_REQUIRED
            job.updated_at = iso_now()
            self.store.upsert(job)
            return job.to_dict()
        except Exception as exc:
            job.state = JobState.FAILED
            job.error = f"[RESCAN_FAILED] {exc}"
            job.updated_at = iso_now()
            self.store.upsert(job)
            raise MobileIntakeError(job.error) from exc

    # -- demo support --------------------------------------------------------
    def queue_demo_file(self, slug: Optional[str] = None) -> dict:
        """Drop a byte-identical demo package photo into the intake folder.

        ``slug`` picks one of the seeded catalogue packs (default Aashirvaad).
        The photo is watermarked DEMO and its barcode belongs to the seeded
        demo catalogue, so the REAL pipeline resolves it — nothing is faked.
        When the watcher is running the file is picked up on the next tick.
        """
        self.ensure_dirs()
        from .demo_image import build_demo_intake_bytes, build_demo_intake_meta

        meta = build_demo_intake_meta(slug)
        data = build_demo_intake_bytes(slug)
        import time, uuid

        filename = f"{DEMO_INPUT_PREFIX}{meta['slug']}-{uuid.uuid4().hex[:8]}-{int(time.time())}.jpg"
        dst = self.watcher.intake_dir / filename
        dst.write_bytes(data)
        return {
            "queued": True,
            "filename": filename,
            "size": len(data),
            "sha256": sha256_bytes(data),
            "demo": True,
            "product": meta,
            "note": (
                f"Demo package photo ({meta['product_name']}) queued for the real "
                "USB-intake pipeline. It is watermarked 'DEMO - NOT A REAL PHOTO'."
            ),
        }

    def reset_demo_state(self) -> dict:
        """Remove demo-generated intake jobs and their on-disk files.

        Deterministic: identical photo bytes -> identical cleanup. Real
        (non-demo) intake files are never touched, model assets are untouched,
        and the demo store's PostgreSQL data is left to the demo-reset script.
        """
        removed_jobs = 0
        removed_files = 0
        for job in self.store.all():
            if not job.demo:
                continue
            if job.stored_path:
                p = self.root / job.stored_path
                try:
                    if p.is_file():
                        p.unlink()
                        removed_files += 1
                except OSError:
                    pass
            self.store.delete(job.job_id)
            removed_jobs += 1
        if self.watcher.intake_dir.is_dir():
            for p in self.watcher.intake_dir.iterdir():
                if p.is_file() and p.name.startswith(DEMO_INPUT_PREFIX):
                    try:
                        p.unlink()
                        removed_files += 1
                    except OSError:
                        pass
        self.store.save()
        return {"removed_jobs": removed_jobs, "removed_files": removed_files}

    # -- helpers ------------------------------------------------------------
    def _require(self, job_id: str) -> IntakeJob:
        job = self.store.get(job_id)
        if job is None:
            raise IntakeJobNotFound(f"No mobile intake job '{job_id}'.")
        return job