"""Storeye Alert entity — persistent, queryable, offline-first alert system.

Alerts are INFORMATIONAL / ACTIONABLE notifications derived from existing
intelligence results (product/shelf intelligence, expiry intelligence,
reconciliation results, camera staleness). They are NEVER an instruction to
mutate inventory: generating an alert creates/updates alert rows only. Inventory
adjustment remains an explicit, human-reviewed operation.

LIFECYCLE
---------
    OPEN                    initial
    ACKNOWLEDGED            human reviewed and acknowledged
    RESOLVED / DISMISSED    terminal (read-only)

Domain transitions:
    OPEN -> ACKNOWLEDGED | RESOLVED | DISMISSED
    ACKNOWLEDGED -> RESOLVED | DISMISSED
    RESOLVED / DISMISSED -> (none)

DEDUPLICATION
-------------
For the same (store, alert_type, product, shelf, camera) context, an existing
OPEN or ACKNOWLISHED alert is updated in place (last_detected_at, confidence,
details) rather than creating an identical alert per camera frame. RESOLVED /
DISMISSED alerts are terminal: the same condition appearing again creates a new
alert.

Severity (INFO/LOW/MEDIUM/HIGH/CRITICAL) and confidence are SEPARATE concepts:
confidence is the AI evidence strength, severity is the business impact.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin

# ---------------------------------------------------------------------------
# Alert types (M16 scope — do not invent more unless architecture requires it)
# ---------------------------------------------------------------------------
ALERT_SHORTAGE = "SHORTAGE"
ALERT_SURPLUS = "SURPLUS"
ALERT_MISPLACEMENT = "MISPLACEMENT"
ALERT_EXPIRY = "EXPIRY"
ALERT_LOW_SHELF_OCCUPANCY = "LOW_SHELF_OCCUPANCY"
ALERT_SHELF_EMPTY = "SHELF_EMPTY"
ALERT_CAMERA_OFFLINE = "CAMERA_OFFLINE"
ALERT_REVIEW_REQUIRED = "REVIEW_REQUIRED"

VALID_ALERT_TYPES = {
    ALERT_SHORTAGE,
    ALERT_SURPLUS,
    ALERT_MISPLACEMENT,
    ALERT_EXPIRY,
    ALERT_LOW_SHELF_OCCUPANCY,
    ALERT_SHELF_EMPTY,
    ALERT_CAMERA_OFFLINE,
    ALERT_REVIEW_REQUIRED,
}

# Severity — business impact. Confidence is NEVER treated as severity.
SEV_INFO = "INFO"
SEV_LOW = "LOW"
SEV_MEDIUM = "MEDIUM"
SEV_HIGH = "HIGH"
SEV_CRITICAL = "CRITICAL"

VALID_SEVERITIES = {SEV_INFO, SEV_LOW, SEV_MEDIUM, SEV_HIGH, SEV_CRITICAL}

# Status lifecycle (see module docstring).
STATUS_OPEN = "OPEN"
STATUS_ACKNOWLEDGED = "ACKNOWLEDGED"
STATUS_RESOLVED = "RESOLVED"
STATUS_DISMISSED = "DISMISSED"

VALID_STATUSES = {
    STATUS_OPEN,
    STATUS_ACKNOWLEDGED,
    STATUS_RESOLVED,
    STATUS_DISMISSED,
}

# Legal transitions; terminal states map to empty sets.
ALLOWED_TRANSITIONS = {
    STATUS_OPEN: {STATUS_ACKNOWLEDGED, STATUS_RESOLVED, STATUS_DISMISSED},
    STATUS_ACKNOWLEDGED: {STATUS_RESOLVED, STATUS_DISMISSED},
    STATUS_RESOLVED: set(),
    STATUS_DISMISSED: set(),
}


class Alert(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "alerts"

    store_id = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    camera_id = mapped_column(
        ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True, index=True
    )
    product_id = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    shelf_id = mapped_column(
        ForeignKey("shelves.id", ondelete="SET NULL"), nullable=True, index=True
    )

    alert_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)

    # AI confidence is EVIDENCE strength, separate from severity.
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Provenance: which intelligence layer produced this alert, and the optional
    # id of the underlying source (e.g. a ReconciliationResult / Batch / camera).
    source_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    source_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    first_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    dismissed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Evidence/metadata: supporting quantities, counting rule, occupancy, etc.
    # References/metadata only — raw video or frames are NEVER stored here.
    details: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    store = relationship("Store")
    camera = relationship("Camera")
    product = relationship("Product")
    shelf = relationship("Shelf")


def default_detected_at() -> datetime:
    return datetime.now(timezone.utc)