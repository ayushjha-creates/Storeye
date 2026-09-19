"""Reconciliation API routes.

AI RULE
-------
Reconciliation compares AI PRODUCT observations against recorded inventory
and produces ReconciliationResult rows. The RESULT is informational only:
POSSIBLE_SHORTAGE / POSSIBLE_SURPLUS are NEVER automatically converted into
inventory mutations. All computation goes through ReconciliationService,
which guarantees it never mutates inventory, creates movements, or creates
batches.

After a run, the router also refreshes SHELF FILL alerts (SHELF_EMPTY /
LOW_SHELF_OCCUPANCY) so that "this shelf is empty / about to get empty, refill
it" surfaces as a reconciliation outcome. That step only writes/updates `alerts`
rows — it still never mutates inventory.
"""

from __future__ import annotations

import logging
from typing import Optional

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..authz import effective_store_id, require_same_store, scoped_get
from ..deps import get_db, require_role
from ...core.auth import ROLE_MANAGER
from ...models import ReconciliationResult, Store, User
from ...schemas import (
    ReconciliationResultList,
    ReconciliationResultRead,
    ReconciliationRunIn,
)
from ...services.alerts import AlertRuleEngine
from ...services.reconciliation import ReconciliationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])


def _require_store(db: Session, current_user: User, store_id: UUID) -> None:
    require_same_store(current_user, store_id)
    if db.get(Store, store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")


@router.post(
    "/run",
    response_model=ReconciliationResultList,
    status_code=status.HTTP_201_CREATED,
)
def run_reconciliation(
    payload: ReconciliationRunIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_MANAGER)),
):
    """Run reconciliation for a store (optionally product/camera scope).

    Persists ReconciliationResult rows and refreshes shelf fill alerts
    (SHELF_EMPTY / LOW_SHELF_OCCUPANCY); inventory is never modified.
    """
    _require_store(db, current_user, payload.store_id)
    svc = ReconciliationService(db)
    results = svc.reconcile_store(
        store_id=payload.store_id,
        start=payload.start,
        end=payload.end,
        product_ids=payload.product_ids,
        camera_id=payload.camera_id,
        min_confidence=payload.min_confidence,
    )
    # Refill alerts are a reconciliation outcome: after comparing AI vs stock,
    # flag shelves that are empty or half full or less. Alerts only, no stock
    # changes. Best-effort so a shelf-alert failure never fails the run.
    try:
        AlertRuleEngine(db).evaluate_shelf_fill(
            store_id=payload.store_id,
            camera_id=payload.camera_id,
            min_confidence=payload.min_confidence,
            trigger="reconciliation",
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("Shelf fill alert refresh after reconciliation failed")
    return ReconciliationResultList(
        items=[ReconciliationResultRead.model_validate(i) for i in results],
        total=len(results),
    )


@router.get("", response_model=ReconciliationResultList)
def list_reconciliation(
    store_id: Optional[UUID] = None,
    product_id: Optional[UUID] = None,
    status_filter: Optional[str] = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    sid = effective_store_id(current_user, store_id)
    stmt = select(ReconciliationResult).where(ReconciliationResult.store_id == sid)
    if product_id is not None:
        stmt = stmt.where(ReconciliationResult.product_id == product_id)
    if status_filter is not None:
        stmt = stmt.where(ReconciliationResult.status == status_filter)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(ReconciliationResult.created_at.desc())).all()
    return ReconciliationResultList(
        items=[ReconciliationResultRead.model_validate(i) for i in items],
        total=total,
    )


@router.get("/{result_id}", response_model=ReconciliationResultRead)
def get_reconciliation_result(
    result_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    return ReconciliationResultRead.model_validate(
        scoped_get(db, current_user, ReconciliationResult, result_id)
    )
