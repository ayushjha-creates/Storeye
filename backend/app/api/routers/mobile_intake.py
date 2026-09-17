"""Mobile-to-Edge USB Intake routes (M25).

The bridge is READ-MOSTLY:
  * `status`        — watcher + directory health
  * `jobs`/`jobs/{id}` — candidate list + detail (never DB-writing)
  * `jobs/{id}/close` — book-keeping AFTER the human confirmed through the
                        existing M17 confirmation endpoint
  * `jobs/{id}/rescan` — re-run the read-only scan over a failed photo
  * `demo-queue`     — demo-mode (+ reset key) helper that pushes a
                       byte-identical, watermark-labelled demo package through
                       the REAL pipeline

There is deliberately NO automatic inventory-mutation endpoint here.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException, status

from ...schemas.mobile_intake import (
    MobileIntakeJobListRead,
    MobileIntakeJobRead,
    MobileIntakeQueueDemoRead,
    MobileIntakeStatusRead,
)
from ...services.mobile_intake import MobileIntakeError, MobileIntakeService
from ...services.mobile_intake.manager import get_intake_manager
from .demo import _require_demo_mode, _require_reset_key

router = APIRouter(prefix="/mobile-intake", tags=["mobile-intake"])


def _manager() -> MobileIntakeService:
    return get_intake_manager()


def _job_response(data: dict) -> MobileIntakeJobRead:
    return MobileIntakeJobRead.from_job_data(data)


@router.get("/status", response_model=MobileIntakeStatusRead)
def intake_status() -> MobileIntakeStatusRead:
    return MobileIntakeStatusRead(**_manager().status())


@router.get("/jobs", response_model=MobileIntakeJobListRead)
def list_jobs() -> MobileIntakeJobListRead:
    items = [_job_response(d) for d in _manager().list_jobs()]
    return MobileIntakeJobListRead(items=items, count=len(items))


@router.get("/jobs/{job_id}", response_model=MobileIntakeJobRead)
def get_job(job_id: str) -> MobileIntakeJobRead:
    try:
        return _job_response(_manager().get_job(job_id))
    except MobileIntakeError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/close", response_model=MobileIntakeJobRead)
def close_job(job_id: str) -> MobileIntakeJobRead:
    """Mark a reviewed job PROCESSED (after the M17 confirm wrote the data)."""
    try:
        return _job_response(_manager().close_job(job_id))
    except MobileIntakeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/rescan", response_model=MobileIntakeJobRead)
def rescan_job(job_id: str) -> MobileIntakeJobRead:
    """Re-run the read-only scan pipeline over a FAILED/REVIEW photo."""
    try:
        return _job_response(_manager().rescan(job_id))
    except MobileIntakeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/demo-queue", response_model=MobileIntakeQueueDemoRead)
def queue_demo_package(
    body: Optional[dict] = None,
    x_demo_reset_key: str = Header(default="", alias="X-Demo-Reset-Key"),
) -> MobileIntakeQueueDemoRead:
    """Queue a watermarked demo package for the REAL intake pipeline.

    Optional JSON body: ``{"product": <demo package slug>}`` selects one of the
    seeded catalogue packs (``aashirvaad`` default, ``amul``, …).
    """
    _require_demo_mode()
    _require_reset_key(x_demo_reset_key)
    slug = (body or {}).get("product")
    return MobileIntakeQueueDemoRead(**_manager().queue_demo_file(slug))