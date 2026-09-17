"""Pydantic schemas for the Mobile-to-Edge USB Intake (M25) API.

Read-mostly: status + job listings. The only mutating endpoints are
`close` (book-keeping after a human confirmed via the M17 flow) and
`rescan` (re-run the read-only scan pipeline over a failed photo). The
inventory/batch write path stays exactly where M17 put it.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

from .batch_intake import BatchScanCandidateRead


class MobileIntakeStatusRead(BaseModel):
    monitoring: bool
    watcher_alive: bool
    intake_dir: str
    processing_dir: str
    processed_dir: str
    failed_dir: str
    watched_at: Optional[str] = None
    started_at: Optional[str] = None
    scans: int = 0
    duplicates: int = 0
    rejected: int = 0
    active_jobs: int = 0
    failed_jobs: int = 0


class MobileIntakeJobRead(BaseModel):
    model_config = ConfigDict(extra="ignore")

    job_id: str
    filename: str
    size: int
    state: str
    demo: bool = False
    duplicate_of: Optional[str] = None
    error: Optional[str] = None
    note: Optional[str] = None
    acceptable: Optional[bool] = None
    reason: Optional[str] = None
    candidate: Optional[BatchScanCandidateRead] = None
    created_at: str
    updated_at: str

    @classmethod
    def from_job_data(cls, data: dict) -> "MobileIntakeJobRead":
        candidate = None
        if data.get("candidate"):
            candidate = BatchScanCandidateRead.model_validate(data["candidate"])
        return cls(
            job_id=data["job_id"],
            filename=data["filename"],
            size=data.get("size", 0),
            state=data["state"],
            demo=data.get("demo", False),
            duplicate_of=data.get("duplicate_of"),
            error=data.get("error"),
            note=data.get("note"),
            acceptable=data.get("acceptable"),
            reason=data.get("reason"),
            candidate=candidate,
            created_at=data["created_at"],
            updated_at=data["updated_at"],
        )


class MobileIntakeJobListRead(BaseModel):
    items: list[MobileIntakeJobRead]
    count: int


class MobileIntakeDemoProductMeta(BaseModel):
    slug: str
    product_name: str
    barcode: str
    batch: str


class MobileIntakeQueueDemoRead(BaseModel):
    queued: bool
    filename: str
    size: int
    sha256: str
    demo: bool = True
    product: Optional[MobileIntakeDemoProductMeta] = None
    note: str