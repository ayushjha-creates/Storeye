"""Storeye Alerts API routes (M16).

Alerts are informational/actionable notifications derived from EXISTING
intelligence results. This router:

    * persists/updates `alerts` rows only — it NEVER mutates inventory,
      inventory_movements, batches, bills or sales;
    * enforces the domain lifecycle (OPEN -> ACKNOWLEDGED -> RESOLVED, or
      OPEN -> DISMISSED) through dedicated endpoints;
    * exposes POST /alerts/evaluate to apply the alert rules over existing
      intelligence without running any camera inference.

The AI -> alert boundary is absolute: no endpoint in this router can modify
inventory. Inventory adjustment stays an explicit, human-reviewed operation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..deps import get_db
from ...schemas import (
    AlertCreate,
    AlertEvaluateIn,
    AlertEvaluateResult,
    AlertList,
    AlertRead,
    AlertUpdate,
)
from ...services.alerts import (
    AlertRuleEngine,
    AlertService,
)

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _get_or_404(db: Session, alert_id: UUID):
    return AlertService(db).get_or_404(alert_id)


@router.get("", response_model=AlertList)
def list_alerts(
    store_id: Optional[UUID] = None,
    camera_id: Optional[UUID] = None,
    product_id: Optional[UUID] = None,
    shelf_id: Optional[UUID] = None,
    alert_type: Optional[str] = Query(
        default=None, description="SHORTAGE|SURPLUS|MISPLACEMENT|EXPIRY|LOW_SHELF_OCCUPANCY|CAMERA_OFFLINE|REVIEW_REQUIRED"
    ),
    severity: Optional[str] = Query(default=None, description="INFO|LOW|MEDIUM|HIGH|CRITICAL"),
    status_filter: Optional[str] = Query(
        default=None, alias="status", description="OPEN|ACKNOWLEDGED|RESOLVED|DISMISSED"
    ),
    created_from: Optional[datetime] = Query(
        default=None, description="Alerts first detected at/after this time (UTC)"
    ),
    created_to: Optional[datetime] = Query(
        default=None, description="Alerts first detected at/before this time (UTC)"
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Paged alert list with filters. Read-only."""
    svc = AlertService(db)
    items, total = svc.query_alerts(
        store_id=store_id,
        camera_id=camera_id,
        product_id=product_id,
        shelf_id=shelf_id,
        alert_type=alert_type,
        severity=severity,
        status=status_filter,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        offset=offset,
    )
    return AlertList(items=[AlertRead.model_validate(a) for a in items], total=total)


@router.post("", response_model=AlertRead, status_code=status.HTTP_201_CREATED)
def create_alert(payload: AlertCreate, db: Session = Depends(get_db)):
    """Manually create an alert (also deduplicates against OPEN/ACKNOWLEDGED
    alerts with the same context). Creates/updates alerts only."""
    svc = AlertService(db)
    alert, _ = svc.create_alert(
        store_id=payload.store_id,
        alert_type=payload.alert_type,
        severity=payload.severity,
        title=payload.title,
        message=payload.message,
        camera_id=payload.camera_id,
        product_id=payload.product_id,
        shelf_id=payload.shelf_id,
        confidence=payload.confidence,
        source_type=payload.source_type,
        source_id=payload.source_id,
        detected_at=payload.detected_at,
        details=payload.details,
    )
    return AlertRead.model_validate(alert)


@router.post("/evaluate", response_model=AlertEvaluateResult)
def evaluate_alerts(payload: AlertEvaluateIn, db: Session = Depends(get_db)):
    """Evaluate EXISTING intelligence, apply the alert rules, deduplicate, and
    return created/updated alerts. Never runs camera inference; never mutates
    inventory/batches/bills/sales."""
    result = AlertRuleEngine(db).evaluate(
        store_id=payload.store_id,
        camera_id=payload.camera_id,
        min_confidence=payload.min_confidence,
        alert_confidence_threshold=payload.alert_confidence_threshold,
        hours=payload.hours,
        expiry_warning_days=payload.expiry_warning_days,
        camera_stale_minutes=payload.camera_stale_minutes,
        reference_date=payload.reference_date,
    )
    return AlertEvaluateResult(
        evaluated_at=result.evaluated_at,
        store_id=payload.store_id,
        hours=result.hours,
        generated=result.generated,
        updated=result.updated,
        skipped=result.skipped,
        alerts=[AlertRead.model_validate(a) for a in result.alerts],
    )


@router.get("/{alert_id}", response_model=AlertRead)
def get_alert(alert_id: UUID, db: Session = Depends(get_db)):
    return AlertRead.model_validate(_get_or_404(db, alert_id))


@router.patch("/{alert_id}", response_model=AlertRead)
def update_alert(alert_id: UUID, payload: AlertUpdate, db: Session = Depends(get_db)):
    """Metadata-only update: title/message/severity/details. Status changes must
    go through the acknowledge/resolve/dismiss endpoints so the lifecycle can
    never be bypassed."""
    svc = AlertService(db)
    alert = _get_or_404(db, alert_id)
    alert = svc.update_fields(
        alert,
        title=payload.title,
        message=payload.message,
        severity=payload.severity,
        details=payload.details,
    )
    return AlertRead.model_validate(alert)


@router.post("/{alert_id}/acknowledge", response_model=AlertRead)
def acknowledge_alert(alert_id: UUID, db: Session = Depends(get_db)):
    return AlertRead.model_validate(AlertService(db).acknowledge(_get_or_404(db, alert_id)))


@router.post("/{alert_id}/resolve", response_model=AlertRead)
def resolve_alert(alert_id: UUID, db: Session = Depends(get_db)):
    return AlertRead.model_validate(AlertService(db).resolve(_get_or_404(db, alert_id)))


@router.post("/{alert_id}/dismiss", response_model=AlertRead)
def dismiss_alert(alert_id: UUID, db: Session = Depends(get_db)):
    return AlertRead.model_validate(AlertService(db).dismiss(_get_or_404(db, alert_id)))