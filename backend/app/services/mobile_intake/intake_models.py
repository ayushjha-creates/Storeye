"""M25 mobile intake job model.

A job is metadata ONLY — the photo bytes themselves never enter PostgreSQL
(M22 constraint: images stay on disk under the intake root). The candidate
produced by the M17 pipeline is snapshotted here so the review screen can
render without re-decoding anything.

Persistence is the filesystem: a single JSON index next to the intake root.
No new database table is required (per M25 "avoid adding DB tables unless
clearly needed").
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional


class JobState(str, Enum):
    DETECTED = "DETECTED"
    WAITING_FOR_COPY = "WAITING_FOR_COPY"
    PROCESSING = "PROCESSING"
    SCANNING = "SCANNING"
    OCR_PROCESSING = "OCR_PROCESSING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    CONFIRMED = "CONFIRMED"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"

    # States that mean "this file's content was already handled" — a new copy
    # of the same bytes must never be received twice.
    TERMINAL_HANDLED = frozenset({REVIEW_REQUIRED, CONFIRMED, PROCESSED})


@dataclass
class IntakeJob:
    job_id: str
    hash: str
    filename: str         # original, sanitised basename as received
    stored_path: str      # relative path under the intake root
    size: int
    state: JobState
    created_at: str       # ISO-8601 (UTC) — JSON friendly
    updated_at: str
    demo: bool = False
    duplicate_of: Optional[str] = None
    error: Optional[str] = None
    candidate: Optional[dict] = None
    reason: Optional[str] = None
    acceptable: Optional[bool] = None
    note: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IntakeJob":
        data = dict(data)
        data["state"] = JobState(data["state"])
        return cls(**data)


class JobsStore:
    """Load/save the in-memory job index to a single atomic JSON file.

    Concurrency model: one application process. All mutations happen inside
    `self._lock`; persistence uses a write-to-tmp + rename so a crash never
    leaves a corrupt index.
    """

    INDEX_NAME = ".storeye-intake-index.json"

    def __init__(self, root) -> None:
        self.root = root
        self.path = root / self.INDEX_NAME
        self._jobs: dict[str, IntakeJob] = {}
        self._lock = __import__("threading").Lock()

    def load(self) -> None:
        if not self.path.exists():
            return
        with self._lock:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return
            self._jobs = {}
            for item in raw.get("jobs", []):
                try:
                    job = IntakeJob.from_dict(item)
                except Exception:
                    continue
                self._jobs[job.job_id] = job

    def save(self) -> None:
        with self._lock:
            payload = {"format": "storeye-mobile-intake-index-v1", "jobs": [j.to_dict() for j in self._jobs.values()]}
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
            tmp.replace(self.path)

    def upsert(self, job: IntakeJob) -> None:
        with self._lock:
            self._jobs[job.job_id] = job

    def get(self, job_id: str) -> Optional[IntakeJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def get_by_hash(self, digest: str) -> Optional[IntakeJob]:
        with self._lock:
            for job in self._jobs.values():
                if job.hash == digest:
                    return job
        return None

    def all(self) -> list[IntakeJob]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.updated_at, reverse=True)
        return jobs

    def delete(self, job_id: str) -> Optional[IntakeJob]:
        with self._lock:
            return self._jobs.pop(job_id, None)

    def clear(self) -> None:
        with self._lock:
            self._jobs = {}


def iso_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")