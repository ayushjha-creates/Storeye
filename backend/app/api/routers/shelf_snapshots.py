"""Periodic Shelf-Occupancy Snapshot API routes (M30).

Endpoints:
    GET /api/shelf-snapshots/summary?store_id=&camera_id=
        — latest snapshot PER region for the shelf-monitor card
    GET /api/shelf-snapshots/history?store_id=&camera_id=&shelf_code=&limit=
        — one shelf's recent history (sparkline/trend)
    GET /api/shelf-snapshots/trend?store_id=&camera_id=&limit=
        — last N snapshots per region (compact trend)
    GET /api/shelf-snapshots/{snapshot_id}
        — a single snapshot row
    GET /api/shelf-snapshots/{snapshot_id}/image?prefer=crop|full
        — stream the on-disk JPEG (path-traversal-guarded)

READ PATH (M30 Layer-A): list/summary/history/trend/services are served from
the runtime's in-memory mirror when it is wired for this store (cache hit) and
fall back to PostgreSQL only on a miss. PostgreSQL is authoritative — the cache
is a speed mirror. Image streaming always reads the DURABLE row because the
on-disk paths are never mirrored.

Every row is store-scoped; list endpoints require `store_id` that matches the
authenticated user's store (403 otherwise), row endpoints return 404 for
other-store rows. Snapshots are OBSERVATIONS — they never mutate inventory.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..authz import require_same_store, scoped_get
from ..deps import get_db, require_role
from ...core.config import get_settings
from ...edge import get_runtime
from ...models import ShelfSnapshot, User
from ...schemas import (
    ShelfHistoryRead,
    ShelfSnapshotRead,
    ShelfSnapshotSummaryRead,
    ShelfStatusCounts,
)

router = APIRouter(prefix="/shelf-snapshots", tags=["shelf-snapshots"])

READ_ROLE = "STAFF"


def _summary_row(snap: ShelfSnapshot) -> ShelfSnapshotRead:
    read = ShelfSnapshotRead.model_validate(snap)
    read.has_image = bool(snap.snapshot_path or snap.crop_path)
    return read


def _cache() -> Optional[object]:
    """The process-wide runtime's shelf mirror (safe to call in tests)."""
    try:
        return get_runtime().get_shelf_snapshot_cache()
    except Exception:  # pragma: no cover - defensive
        return None


def _cache_hits(store_id: UUID, camera_id: UUID) -> bool:
    """True when the store-scoped mirror has entries for this camera.

    The runtime is store-scoped; a mirror that belongs to a different store is
    ignored so stale cross-store rows are never served.
    """
    try:
        runtime = get_runtime()
        if str(runtime.store_id) != str(store_id):
            return False
        cache = runtime.get_shelf_snapshot_cache()
        return len(cache.latest(str(store_id), str(camera_id))) > 0
    except Exception:  # pragma: no cover - defensive
        return False


def _from_cache_read(read: dict) -> ShelfSnapshotRead:
    return ShelfSnapshotRead.model_validate(read)


@router.get("/summary", response_model=ShelfSnapshotSummaryRead)
def shelf_summary(
    store_id: UUID,
    camera_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(READ_ROLE)),
):
    """Latest snapshot per region for one camera (the monitor card payload).

    M30 Layer-A: reads from the in-memory mirror when the cache is store-scoped
    and already holds entries for this camera; otherwise falls back to SQL.
    PostgreSQL is authoritative — the cache is a read-speed mirror.
    """
    require_same_store(current_user, store_id)
    if _cache_hits(store_id, camera_id):
        latest_map = _cache().latest(str(store_id), str(camera_id))
        if latest_map:
            items, counts = [], ShelfStatusCounts()
            for entry in latest_map.values():
                items.append(_from_cache_read(entry.to_read_dict()))
                if entry.occluded:
                    counts.OCCLUDED += 1
                elif entry.status == "EMPTY":
                    counts.EMPTY += 1
                elif entry.status == "LOW":
                    counts.LOW += 1
                elif entry.status == "MEDIUM":
                    counts.MEDIUM += 1
                elif entry.status == "FULL":
                    counts.FULL += 1
            items.sort(key=lambda r: r.observed_at, reverse=True)
            return ShelfSnapshotSummaryRead(
                items=items, status=counts, total_regions=len(items),
                last_scan_at=items[0].observed_at if items else None,
            )
    latest_ids = select(
        ShelfSnapshot.camera_id,
        ShelfSnapshot.shelf_code,
        func.max(ShelfSnapshot.observed_at).label("observed_at"),
    ).where(
        ShelfSnapshot.store_id == store_id,
        ShelfSnapshot.camera_id == camera_id,
    ).group_by(
        ShelfSnapshot.camera_id, ShelfSnapshot.shelf_code
    ).subquery()
    rows = (
        db.execute(
            select(ShelfSnapshot)
            .join(
                latest_ids,
                (latest_ids.c.camera_id == ShelfSnapshot.camera_id)
                & (latest_ids.c.shelf_code == ShelfSnapshot.shelf_code)
                & (latest_ids.c.observed_at == ShelfSnapshot.observed_at),
            )
            .order_by(ShelfSnapshot.observed_at.desc())
        )
        .scalars()
        .all()
    )
    if not rows:
        return ShelfSnapshotSummaryRead(items=[], total_regions=0)
    latest = sorted(rows, key=lambda r: r.observed_at, reverse=True)
    counts = ShelfStatusCounts()
    for r in latest:
        if r.occluded:
            counts.OCCLUDED += 1
        elif r.status == "EMPTY":
            counts.EMPTY += 1
        elif r.status == "LOW":
            counts.LOW += 1
        elif r.status == "MEDIUM":
            counts.MEDIUM += 1
        elif r.status == "FULL":
            counts.FULL += 1
    return ShelfSnapshotSummaryRead(
        items=[_summary_row(r) for r in latest], status=counts,
        total_regions=len(latest), last_scan_at=latest[0].observed_at,
    )


@router.get("/history", response_model=ShelfHistoryRead)
def shelf_history(
    store_id: UUID,
    camera_id: UUID,
    shelf_code: str = Query(..., min_length=1, max_length=30),
    limit: int = Query(default=24, ge=1, le=200),
    before: Optional[datetime] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(READ_ROLE)),
):
    """Recent snapshot history for a single shelf region (sparkline data).

    M30 Layer-A: cache-first with SQL fallback (image paths not mirrored).
    """
    require_same_store(current_user, store_id)
    if _cache_hits(store_id, camera_id):
        cached = _cache().history(str(store_id), str(camera_id), shelf_code, limit=limit)
        if cached:
            items = [_from_cache_read(e.to_read_dict()) for e in cached]
            return ShelfHistoryRead(
                shelf_code=shelf_code, camera_id=camera_id,
                items=items, total=len(items),
            )
    stmt = (
        select(ShelfSnapshot)
        .where(
            ShelfSnapshot.store_id == store_id,
            ShelfSnapshot.camera_id == camera_id,
            ShelfSnapshot.shelf_code == shelf_code,
        )
        .order_by(ShelfSnapshot.observed_at.desc())
        .limit(limit)
    )
    if before is not None:
        stmt = stmt.where(ShelfSnapshot.observed_at < before)
    rows = db.execute(stmt).scalars().all()
    return ShelfHistoryRead(
        shelf_code=shelf_code, camera_id=camera_id,
        items=[_summary_row(r) for r in rows], total=len(rows),
    )


@router.get("/trend", response_model=ShelfSnapshotSummaryRead)
def shelf_trend(
    store_id: UUID,
    camera_id: UUID,
    limit: int = Query(default=48, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(READ_ROLE)),
):
    """Last `limit` snapshots PER region (compact trend window)."""
    require_same_store(current_user, store_id)
    if _cache_hits(store_id, camera_id):
        cached = _cache().trend(str(store_id), str(camera_id), limit=limit)
        if cached:
            items, counts = [], ShelfStatusCounts()
            for e in cached:
                items.append(_from_cache_read(e.to_read_dict()))
                if e.occluded:
                    counts.OCCLUDED += 1
                elif e.status == "EMPTY":
                    counts.EMPTY += 1
                elif e.status == "LOW":
                    counts.LOW += 1
                elif e.status == "MEDIUM":
                    counts.MEDIUM += 1
                elif e.status == "FULL":
                    counts.FULL += 1
            return ShelfSnapshotSummaryRead(
                items=items, status=counts, total_regions=len(items),
                last_scan_at=items[0].observed_at if items else None,
            )
    rows = (
        db.execute(
            select(ShelfSnapshot)
            .where(
                ShelfSnapshot.store_id == store_id,
                ShelfSnapshot.camera_id == camera_id,
            )
            .order_by(ShelfSnapshot.observed_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    items = [_summary_row(r) for r in rows]
    counts = ShelfStatusCounts()
    for r in rows:
        if r.occluded:
            counts.OCCLUDED += 1
        elif r.status == "EMPTY":
            counts.EMPTY += 1
        elif r.status == "LOW":
            counts.LOW += 1
        elif r.status == "MEDIUM":
            counts.MEDIUM += 1
        elif r.status == "FULL":
            counts.FULL += 1
    return ShelfSnapshotSummaryRead(
        items=items, status=counts, total_regions=len(rows),
        last_scan_at=rows[0].observed_at if rows else None,
    )


@router.get("/{snapshot_id}", response_model=ShelfSnapshotRead)
def shelf_snapshot_one(
    snapshot_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(READ_ROLE)),
):
    cache = _cache()
    if cache is not None:
        entry = cache.get_by_id(str(snapshot_id))
        if entry is not None:
            # Preserve the scoped-get guarantee: never serve another store's row.
            from ..authz import effective_store_id
            if str(entry.store_id) == str(effective_store_id(current_user, None)):
                return _from_cache_read(entry.to_read_dict())
    snap = scoped_get(db, current_user, ShelfSnapshot, snapshot_id)
    return _summary_row(snap)


@router.get("/{snapshot_id}/image")
def shelf_snapshot_image(
    snapshot_id: UUID,
    prefer: str = Query(default="crop", pattern="^(crop|full)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(READ_ROLE)),
):
    """Stream the snapshot JPEG from disk (never from PostgreSQL)."""
    snap = scoped_get(db, current_user, ShelfSnapshot, snapshot_id)
    settings = get_settings()
    root = settings.SHELF_SNAPSHOT_DIR.resolve()
    # Prefer the requested file; fall back to whichever image exists.
    if prefer == "full":
        candidate_path = snap.snapshot_path or snap.crop_path
    else:
        candidate_path = snap.crop_path or snap.snapshot_path
    if not candidate_path:
        raise HTTPException(status_code=404, detail="Snapshot has no stored image.")
    candidate = (root / candidate_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise HTTPException(
            status_code=404, detail="Snapshot path escapes the snapshot root."
        )
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Snapshot image is no longer on disk.")
    return FileResponse(candidate, media_type="image/jpeg")