"""Pydantic schemas for Store Intelligence (M20).

Insights are OPERATIONAL observations with evidence + recommended actions.
They are distinct from M16 alerts: insights explain "why", alerts demand
attention. Neither layer ever mutates inventory/batches/sales.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ..models.insight import (
    VALID_CATEGORIES,
    VALID_STATUSES,
    VALID_INSIGHT_TYPES,
    VALID_SEVERITIES,
)
from ..services.insights import VALID_STORE_HEALTH_STATES


def _check(value: str, choices: set, name: str) -> str:
    if value not in choices:
        raise ValueError(
            f"{name} must be one of {sorted(choices)}, got {value!r}"
        )
    return value


class InsightRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    category: str
    insight_type: str
    severity: str
    status: str
    title: str
    description: Optional[str] = None
    rule_id: str
    source_modules: Optional[list[str]] = None
    evidence: Optional[dict[str, Any]] = None
    recommended_action: Optional[str] = None
    certainty: str
    entity_type: str
    entity_id: str
    product_id: Optional[UUID] = None
    shelf_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    camera_id: Optional[UUID] = None
    first_detected_at: datetime
    last_detected_at: datetime
    expires_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    expired_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class InsightList(BaseModel):
    items: list[InsightRead]
    total: int


class InsightSummary(BaseModel):
    """Aggregate insight counts for the store (dashboard/API filters)."""

    store_id: UUID
    total: int
    open: int
    acknowledged: int
    high_priority: int  # active (open+acknowledged) HIGH/CRITICAL severity
    inventory: int
    shelf: int
    expiry: int
    customer_flow: int
    camera: int
    store_health: int
    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}


class InsightEvaluateIn(BaseModel):
    """Evaluate existing persisted data against the insight rules.

    This operation never runs camera inference, never communicates with a
    cloud service, and never mutates inventory/batches/sales. It only reads
    persisted data and writes/updates `insights` (and optional M16 `alerts`
    at/above the configured actionable severity).
    """

    store_id: UUID
    # Deterministic evaluation anchor for reproducible tests; otherwise today UTC.
    reference_date: Optional[date] = None
    # Optional explicit "now"; defaults to the server clock.
    now: Optional[datetime] = None


class InsightEvaluateResult(BaseModel):
    evaluated_at: datetime
    store_id: UUID
    candidates: int
    created: int
    refreshed: int
    resolved: int
    expired: int
    alerts_created: int
    alerts_updated: int
    insights: list[InsightRead]

    @classmethod
    def from_service(cls, result, insights: list[InsightRead]) -> "InsightEvaluateResult":
        return cls(
            evaluated_at=result.evaluated_at,
            store_id=result.store_id,
            candidates=result.candidates,
            created=result.created,
            refreshed=result.refreshed,
            resolved=result.resolved,
            expired=result.expired,
            alerts_created=result.alerts_created,
            alerts_updated=result.alerts_updated,
            insights=insights,
        )


class InsightStatusIn(BaseModel):
    """Acknowledge / resolve / expire an insight (lifecycle is domain-validated)."""

    store_id: UUID


class StoreHealthMetrics(BaseModel):
    """Explicit, documented KPI container for the Store Health summary.

    Every value is derived from existing data with a documented formula (see
    docs/milestone_20_store_intelligence.md). No opaque score is returned.
    """

    store_id: UUID
    state: str  # HEALTHY | ATTENTION | CRITICAL
    basis: list[str] = []  # human-readable reasons behind the state
    cameras: dict[str, Any] = {}  # total/offline/healthy/healthy_pct
    inventory: dict[str, Any] = {}  # total/low/out_of_stock/healthy_pct
    shelf: dict[str, Any] = {}  # known/low_or_empty/visibility_pct
    alerts: dict[str, Any] = {}  # open
    expiry: dict[str, Any] = {}  # expired/expiring_soon
    customer_flow: dict[str, Any] = {}  # total visitors / active now
    edge: dict[str, Any] = {}  # online / offline_cameras
    evaluated_at: Optional[datetime] = None

    def model_post_init(self, __context: Any) -> None:
        _check(self.state, VALID_STORE_HEALTH_STATES, "state")


class InsightFilterIn(BaseModel):
    """Validated list filters shared by the insight endpoints."""

    type: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = None
    category: Optional[str] = None
    product_id: Optional[UUID] = None
    shelf_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    camera_id: Optional[UUID] = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)

    def model_post_init(self, __context: Any) -> None:
        if self.type is not None:
            _check(self.type, VALID_INSIGHT_TYPES, "type")
        if self.severity is not None:
            _check(self.severity, VALID_SEVERITIES, "severity")
        if self.status is not None:
            _check(self.status, VALID_STATUSES, "status")
        if self.category is not None:
            _check(self.category, VALID_CATEGORIES, "category")