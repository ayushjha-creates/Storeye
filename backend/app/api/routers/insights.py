"""Store Intelligence API routes (M20).

Endpoints:
    GET  /api/insights                       — paged, filterable insight list
    GET  /api/insights/summary               — aggregate counts by category/severity
    GET  /api/insights/store-health          — categorical store health summary
    GET  /api/insights/inventory             — inventory-domain insights (paged)
    GET  /api/insights/expiry                — expiry-domain insights (paged)
    GET  /api/insights/customer-flow         — customer-flow insights (paged)
    POST /api/insights/evaluate              — run the insight rules (on-demand)
    GET  /api/insights/{insight_id}          — one insight with its evidence
    POST /api/insights/{insight_id}/acknowledge
    POST /api/insights/{insight_id}/resolve
    POST /api/insights/{insight_id}/expire

Guarantees (mirrors the M16 alert boundary):
    * evaluation reads EXISTING persisted data only (no new CV pipeline),
    * evaluation writes/updates `insights` rows and, at configured actionable
      severity, M16 `alerts` via the standard deduplication — it NEVER mutates
      inventory, batches, sales or bills,
    * customer-flow insights use aggregate M19 journey analytics; people flow
      is never translated into purchase intent.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..authz import effective_store_id, require_same_store, scoped_get
from ..deps import get_db, require_role
from ...core.auth import ROLE_MANAGER
from ...models import Insight, User, STATUS_OPEN, STATUS_ACKNOWLEDGED
from ...schemas import (
    InsightEvaluateIn,
    InsightEvaluateResult,
    InsightList,
    InsightRead,
    InsightSummary,
    StoreHealthMetrics,
)
from ...services.insights import InsightEngine, StoreHealthService

router = APIRouter(prefix="/insights", tags=["insights"])


def _list_query(
    db: Session,
    *,
    store_id: UUID,
    category: Optional[str] = None,
    insight_type: Optional[str] = None,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    product_id: Optional[UUID] = None,
    zone_id: Optional[UUID] = None,
    camera_id: Optional[UUID] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Insight], int]:
    conds = [Insight.store_id == store_id]
    if category:
        conds.append(Insight.category == category)
    if insight_type:
        conds.append(Insight.insight_type == insight_type)
    if severity:
        conds.append(Insight.severity == severity)
    if status:
        conds.append(Insight.status == status)
    if product_id:
        conds.append(Insight.product_id == product_id)
    if zone_id:
        conds.append(Insight.zone_id == zone_id)
    if camera_id:
        conds.append(Insight.camera_id == camera_id)

    base = select(Insight).where(*conds)
    total = int(db.scalar(select(func.count()).select_from(base.subquery())) or 0)
    items = list(
        db.scalars(
            base.order_by(Insight.last_detected_at.desc())
            .limit(int(limit))
            .offset(int(offset))
        )
    )
    return items, total


@router.get("", response_model=InsightList)
def list_insights(
    store_id: UUID,
    category: Optional[str] = Query(default=None, description="inventory|shelf|expiry|customer_flow|camera|store_health"),
    type_filter: Optional[str] = Query(default=None, alias="type"),
    severity: Optional[str] = Query(default=None, description="INFO|LOW|MEDIUM|HIGH|CRITICAL"),
    status_filter: Optional[str] = Query(default=None, alias="status", description="OPEN|ACKNOWLEDGED|RESOLVED|EXPIRED"),
    product_id: Optional[UUID] = None,
    zone_id: Optional[UUID] = None,
    camera_id: Optional[UUID] = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    """Paged insight list with filters. Read-only."""
    require_same_store(current_user, store_id)
    items, total = _list_query(
        db,
        store_id=store_id,
        category=category,
        insight_type=type_filter,
        severity=severity,
        status=status_filter,
        product_id=product_id,
        zone_id=zone_id,
        camera_id=camera_id,
        limit=limit,
        offset=offset,
    )
    return InsightList(items=[InsightRead.model_validate(i) for i in items], total=total)


@router.get("/summary", response_model=InsightSummary)
def insights_summary(
    store_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    """Aggregate insight counts for dashboard KPIs."""
    require_same_store(current_user, store_id)
    rows = db.execute(
        select(Insight.category, Insight.status, Insight.severity, func.count().label("cnt"))
        .where(Insight.store_id == store_id)
        .group_by(Insight.category, Insight.status, Insight.severity)
    ).all()

    total = 0
    open_count = 0
    ack_count = 0
    high_priority = 0
    by_type: dict = {}
    by_severity: dict = {}
    category_counts = {c: 0 for c in ("inventory", "shelf", "expiry", "customer_flow", "camera", "store_health")}

    for cat, st, sev, cnt in rows:
        total += cnt
        category_counts[cat] = category_counts.get(cat, 0) + cnt
        by_type[cat] = category_counts[cat]
        by_severity[sev] = by_severity.get(sev, 0) + cnt
        if st == STATUS_OPEN:
            open_count += cnt
        elif st == STATUS_ACKNOWLEDGED:
            ack_count += cnt
        if st in (STATUS_OPEN, STATUS_ACKNOWLEDGED) and sev in ("HIGH", "CRITICAL"):
            high_priority += cnt

    return InsightSummary(
        store_id=store_id,
        total=total,
        open=open_count,
        acknowledged=ack_count,
        high_priority=high_priority,
        inventory=category_counts.get("inventory", 0),
        shelf=category_counts.get("shelf", 0),
        expiry=category_counts.get("expiry", 0),
        customer_flow=category_counts.get("customer_flow", 0),
        camera=category_counts.get("camera", 0),
        store_health=category_counts.get("store_health", 0),
        by_type=by_type,
        by_severity=by_severity,
    )


@router.get("/store-health", response_model=StoreHealthMetrics)
def store_health_endpoint(
    store_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    """Categorical store health (HEALTHY/ATTENTION/CRITICAL) with explicit,
    documented evidence (no opaque score)."""
    require_same_store(current_user, store_id)
    health = StoreHealthService(db).compute(store_id)
    return StoreHealthMetrics(
        store_id=store_id,
        state=health.state,
        basis=health.basis,
        cameras=health.cameras,
        inventory=health.inventory,
        shelf=health.shelf,
        alerts=health.alerts,
        expiry=health.expiry,
        customer_flow=health.customer_flow,
        edge=health.edge,
        evaluated_at=datetime.now().astimezone(),
    )


@router.get("/inventory", response_model=InsightList)
def inventory_insights(
    store_id: UUID,
    insight_type: Optional[str] = Query(default=None, description="LOW_STOCK|OUT_OF_STOCK|HIGH_SELLING_LOW_STOCK|LOW_STOCK_WITH_LOW_SHELF_AVAILABILITY"),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    product_id: Optional[UUID] = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    require_same_store(current_user, store_id)
    items, total = _list_query(
        db,
        store_id=store_id,
        category="inventory",
        insight_type=insight_type,
        status=status_filter,
        product_id=product_id,
        limit=limit,
        offset=offset,
    )
    return InsightList(items=[InsightRead.model_validate(i) for i in items], total=total)


@router.get("/expiry", response_model=InsightList)
def expiry_insights(
    store_id: UUID,
    insight_type: Optional[str] = Query(default=None, description="EXPIRY_RISK|EXPIRED_BATCH|STOCK_ROTATION_RECOMMENDATION"),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    product_id: Optional[UUID] = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    require_same_store(current_user, store_id)
    items, total = _list_query(
        db,
        store_id=store_id,
        category="expiry",
        insight_type=insight_type,
        status=status_filter,
        product_id=product_id,
        limit=limit,
        offset=offset,
    )
    return InsightList(items=[InsightRead.model_validate(i) for i in items], total=total)


@router.get("/customer-flow", response_model=InsightList)
def customer_flow_insights(
    store_id: UUID,
    insight_type: Optional[str] = Query(default=None, description="HIGH_TRAFFIC_ZONE|HIGH_DWELL_ZONE|HIGH_TRAFFIC_LOW_SHELF_AVAILABILITY"),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    zone_id: Optional[UUID] = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    require_same_store(current_user, store_id)
    items, total = _list_query(
        db,
        store_id=store_id,
        category="customer_flow",
        insight_type=insight_type,
        status=status_filter,
        zone_id=zone_id,
        limit=limit,
        offset=offset,
    )
    return InsightList(items=[InsightRead.model_validate(i) for i in items], total=total)


@router.post("/evaluate", response_model=InsightEvaluateResult)
def evaluate_insights(
    payload: InsightEvaluateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_MANAGER)),
):
    """Run the insight rules against EXISTING data (on-demand). Deterministic;
    never runs camera inference; never mutates inventory/batches/sales."""
    require_same_store(current_user, payload.store_id)
    result = InsightEngine(db).evaluate(
        store_id=payload.store_id,
        reference_date=payload.reference_date,
        now=payload.now,
    )
    return InsightEvaluateResult.from_service(
        result,
        [InsightRead.model_validate(i) for i in result.insights],
    )


@router.get("/{insight_id}", response_model=InsightRead)
def get_insight(
    insight_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    """One insight with its full evidence (the 'Why?'). Read-only."""
    return InsightRead.model_validate(scoped_get(db, current_user, Insight, insight_id))


def _transition(db: Session, insight: Insight, new_status: str) -> Insight:
    allowed = {
        "OPEN": {"ACKNOWLEDGED", "RESOLVED", "EXPIRED"},
        "ACKNOWLEDGED": {"RESOLVED", "EXPIRED"},
        "RESOLVED": set(),
        "EXPIRED": set(),
    }
    if new_status not in allowed.get(insight.status, set()):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Cannot transition insight from {insight.status} to {new_status} "
                f"(allowed: {sorted(allowed.get(insight.status, set())) or 'none'})"
            ),
        )
    now = datetime.now().astimezone()
    insight.status = new_status
    if new_status == "ACKNOWLEDGED":
        insight.acknowledged_at = now
    elif new_status == "RESOLVED":
        insight.resolved_at = now
    elif new_status == "EXPIRED":
        insight.expired_at = now
    insight.updated_at = now
    db.commit()
    db.refresh(insight)
    return insight


@router.post("/{insight_id}/acknowledge", response_model=InsightRead)
def acknowledge_insight(
    insight_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_MANAGER)),
):
    return InsightRead.model_validate(
        _transition(db, scoped_get(db, current_user, Insight, insight_id), "ACKNOWLEDGED")
    )


@router.post("/{insight_id}/resolve", response_model=InsightRead)
def resolve_insight(
    insight_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_MANAGER)),
):
    return InsightRead.model_validate(
        _transition(db, scoped_get(db, current_user, Insight, insight_id), "RESOLVED")
    )


@router.post("/{insight_id}/expire", response_model=InsightRead)
def expire_insight(
    insight_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_MANAGER)),
):
    return InsightRead.model_validate(
        _transition(db, scoped_get(db, current_user, Insight, insight_id), "EXPIRED")
    )