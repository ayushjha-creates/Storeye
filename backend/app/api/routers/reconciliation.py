"""Reconciliation API routes.

AI RULE
-------
Reconciliation compares AI PRODUCT observations against recorded inventory
and produces ReconciliationResult rows. The RESULT is informational only:
POSSIBLE_SHORTAGE / POSSIBLE_SURPLUS are NEVER automatically converted into
inventory mutations. All computation goes through ReconciliationService,
which guarantees it never mutates inventory, creates movements, or creates
batches.
"""

from __future__ import annotations

from typing import Optional

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..deps import get_db
from ...models import ReconciliationResult, Store
from ...schemas import (
    ReconciliationResultList,
    ReconciliationResultRead,
    ReconciliationRunIn,
)
from ...services.reconciliation import ReconciliationService

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])


def _require_store(db: Session, store_id: UUID) -> None:
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
):
    """Run reconciliation for a store (optionally product/camera scope).

    Persists ReconciliationResult rows only; inventory is never modified.
    """
    _require_store(db, payload.store_id)
    svc = ReconciliationService(db)
    results = svc.reconcile_store(
        store_id=payload.store_id,
        start=payload.start,
        end=payload.end,
        product_ids=payload.product_ids,
        camera_id=payload.camera_id,
        min_confidence=payload.min_confidence,
    )
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
):
    stmt = select(ReconciliationResult)
    if store_id is not None:
        stmt = stmt.where(ReconciliationResult.store_id == store_id)
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
):
    result = db.get(ReconciliationResult, result_id)
    if result is None:
        raise HTTPException(
            status_code=404, detail="Reconciliation result not found"
        )
    return ReconciliationResultRead.model_validate(result)
