"""Pydantic schemas for the Alert centre (M16).

Alerts are informational/actionable notifications. Creating or updating an
alert NEVER mutates inventory/batches/bills/sales — those stay explicit,
human-reviewed operations.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ..models.alert import (
    VALID_ALERT_TYPES,
    VALID_SEVERITIES,
)


def _check(value: str, choices: set, name: str) -> str:
    if value not in choices:
        raise ValueError(
            f"{name} must be one of {sorted(choices)}, got {value!r}"
        )
    return value


class AlertCreate(BaseModel):
    """Create an alert manually. Deduplicated like rule-generated alerts."""

    store_id: UUID
    alert_type: str
    severity: str
    title: str = Field(..., min_length=1, max_length=200)
    message: Optional[str] = Field(default=None, max_length=2000)
    camera_id: Optional[UUID] = None
    product_id: Optional[UUID] = None
    shelf_id: Optional[UUID] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    detected_at: Optional[datetime] = None
    details: Optional[dict[str, Any]] = None

    def model_post_init(self, __context: Any) -> None:
        _check(self.alert_type, VALID_ALERT_TYPES, "alert_type")
        _check(self.severity, VALID_SEVERITIES, "severity")


class AlertUpdate(BaseModel):
    """Metadata-only update (title/message/severity/details). Status changes are
    handled exclusively by the acknowledge/resolve/dismiss endpoints so the
    domain lifecycle can never be bypassed."""

    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    message: Optional[str] = Field(default=None, min_length=1, max_length=2000)
    severity: Optional[str] = None
    details: Optional[dict[str, Any]] = None

    def model_post_init(self, __context: Any) -> None:
        if self.severity is not None:
            _check(self.severity, VALID_SEVERITIES, "severity")


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    camera_id: Optional[UUID] = None
    product_id: Optional[UUID] = None
    shelf_id: Optional[UUID] = None
    alert_type: str
    severity: str
    status: str
    title: str
    message: Optional[str] = None
    confidence: Optional[float] = None
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    first_detected_at: datetime
    last_detected_at: datetime
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    dismissed_at: Optional[datetime] = None
    details: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime


class AlertList(BaseModel):
    items: list[AlertRead]
    total: int


class AlertEvaluateIn(BaseModel):
    """Evaluate EXISTING intelligence results and apply the alert rules.

    This operation never runs camera inference and never touches the network:
    it reads persisted observations/intelligence and writes/updates alerts only.
    """

    store_id: UUID
    camera_id: Optional[UUID] = None
    # Observation-confidence floor used by the shared M15 counting.
    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    # Alert-generation confidence threshold (evidence strength), separate from
    # severity. Conservative default: alerts need solid AI evidence.
    alert_confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    hours: int = Field(default=24, ge=1, le=168)
    # Expiry window (days) — defaults to app setting EXPIRY_WARNING_DAYS.
    expiry_warning_days: Optional[int] = Field(default=None, ge=0, le=3650)
    # Camera staleness (minutes) — observations-based heartbeat proxy.
    camera_stale_minutes: int = Field(default=60, ge=1, le=24 * 60 * 30)
    # Deterministic reference date for tests; defaults to today UTC.
    reference_date: Optional[date] = None


class AlertEvaluateResult(BaseModel):
    evaluated_at: datetime
    store_id: UUID
    hours: int
    generated: int  # newly created alerts
    updated: int  # deduplicated (existing OPEN/ACKNOWLEDGED alert refreshed)
    skipped: int  # evaluated but below thresholds / insufficient evidence
    alerts: list[AlertRead]