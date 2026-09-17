"""Storeye Insight entity — M20 Store Intelligence.

An Insight is a deterministic, evidence-backed operational observation derived
from EXISTING persisted data (inventory, batches, shelf/product intelligence,
alerts, anonymous customer journeys). It answers "what does the available data
suggest operationally" and carries a recommended action. An Insight is NOT an
Alert: alerts signal *something requiring attention* (M16); insights explain
*what the data suggests and what to do about it*.

RELATIONSHIP TO ALERTS
----------------------
Insights and alerts are related but distinct. An insight persists evidence,
rule provenance (rule_id), source modules and a recommended action so the
"why" is never lost. At a configured actionable severity an insight MAY also
create/refresh an M16 alert through the standard AlertService deduplication —
it never spawns a second alert system.

LIFECYCLE
---------
    OPEN          initial
    ACKNOWLEDGED  human reviewed
    RESOLVED      underlying condition no longer holds
    EXPIRED       TTL passed while still open (e.g. an expiry insight outlived
                  the threshold window)

DEDUPLICATION
-------------
A candidate insight is identified by (store_id, insight_type, entity_type,
entity_id). An existing OPEN/ACKNOWLEDGED insight with the same key is refreshed
in place (last_detected_at, evidence, severity). RESOLVED/EXPIRED insights are
terminal: the same condition re-appearing later creates a NEW insight. This is
deterministic: evaluation cycles never create unlimited duplicates.

STORAGE GUARANTEES
------------------
Insights store evidence and metadata only. They NEVER store raw images or Re-ID
embeddings, and the evaluation engine NEVER mutates inventory, batches, sales,
bills or movements (M19 privacy architecture intact).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin

# ---------------------------------------------------------------------------
# Categories — the grouping the UI/dashboards filter by.
# ---------------------------------------------------------------------------
CATEGORY_INVENTORY = "inventory"
CATEGORY_SHELF = "shelf"
CATEGORY_EXPIRY = "expiry"
CATEGORY_CUSTOMER_FLOW = "customer_flow"
CATEGORY_CAMERA = "camera"
CATEGORY_STORE_HEALTH = "store_health"

VALID_CATEGORIES = {
    CATEGORY_INVENTORY,
    CATEGORY_SHELF,
    CATEGORY_EXPIRY,
    CATEGORY_CUSTOMER_FLOW,
    CATEGORY_CAMERA,
    CATEGORY_STORE_HEALTH,
}

# ---------------------------------------------------------------------------
# Insight types — only types backed by actual data are ever produced.
# ---------------------------------------------------------------------------
INSIGHT_LOW_STOCK = "LOW_STOCK"
INSIGHT_OUT_OF_STOCK = "OUT_OF_STOCK"
INSIGHT_LOW_STOCK_LOW_SHELF = "LOW_STOCK_WITH_LOW_SHELF_AVAILABILITY"
INSIGHT_HIGH_SELLING_LOW_STOCK = "HIGH_SELLING_LOW_STOCK"
INSIGHT_EXPIRY_RISK = "EXPIRY_RISK"
INSIGHT_EXPIRED_BATCH = "EXPIRED_BATCH"
INSIGHT_STOCK_ROTATION = "STOCK_ROTATION_RECOMMENDATION"
INSIGHT_LOW_SHELF_AVAILABILITY = "LOW_SHELF_AVAILABILITY"
INSIGHT_MISPLACEMENT = "MISPLACEMENT"
INSIGHT_HIGH_TRAFFIC_ZONE = "HIGH_TRAFFIC_ZONE"
INSIGHT_HIGH_DWELL_ZONE = "HIGH_DWELL_ZONE"
INSIGHT_HIGH_TRAFFIC_LOW_SHELF = "HIGH_TRAFFIC_LOW_SHELF_AVAILABILITY"
INSIGHT_CAMERA_HEALTH = "CAMERA_HEALTH"
INSIGHT_INVENTORY_RISK = "INVENTORY_RISK"
INSIGHT_STORE_HEALTH = "STORE_HEALTH"

# Aggregate/recommendation-only types that are never emitted directly by a
# leaf rule unless real evidence exists for them.
VALID_INSIGHT_TYPES = {
    INSIGHT_LOW_STOCK,
    INSIGHT_OUT_OF_STOCK,
    INSIGHT_LOW_STOCK_LOW_SHELF,
    INSIGHT_HIGH_SELLING_LOW_STOCK,
    INSIGHT_EXPIRY_RISK,
    INSIGHT_EXPIRED_BATCH,
    INSIGHT_STOCK_ROTATION,
    INSIGHT_LOW_SHELF_AVAILABILITY,
    INSIGHT_MISPLACEMENT,
    INSIGHT_HIGH_TRAFFIC_ZONE,
    INSIGHT_HIGH_DWELL_ZONE,
    INSIGHT_HIGH_TRAFFIC_LOW_SHELF,
    INSIGHT_CAMERA_HEALTH,
    INSIGHT_INVENTORY_RISK,
    INSIGHT_STORE_HEALTH,
}

# Severity — business impact, reused from the M16 scale. Evidence strength is
# carried separately as `certainty`.
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
STATUS_EXPIRED = "EXPIRED"

VALID_STATUSES = {
    STATUS_OPEN,
    STATUS_ACKNOWLEDGED,
    STATUS_RESOLVED,
    STATUS_EXPIRED,
}

# Legal transitions; terminal states map to empty sets.
ALLOWED_TRANSITIONS = {
    STATUS_OPEN: {STATUS_ACKNOWLEDGED, STATUS_RESOLVED, STATUS_EXPIRED},
    STATUS_ACKNOWLEDGED: {STATUS_RESOLVED, STATUS_EXPIRED},
    STATUS_RESOLVED: set(),
    STATUS_EXPIRED: set(),
}

# Evidence-strength category (separate from severity).
CERTAINTY_HIGH = "HIGH"
CERTAINTY_MEDIUM = "MEDIUM"
CERTAINTY_LOW = "LOW"
VALID_CERTAINTIES = {CERTAINTY_HIGH, CERTAINTY_MEDIUM, CERTAINTY_LOW}


class Insight(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "insights"
    __table_args__ = (
        # Dedup is enforced at the application layer (InsightEngine) exactly
        # like AlertService: only one active (OPEN/ACKNOWLEDGED) insight per
        # (store_id, insight_type, dedupe_key). RESOLVED/EXPIRED rows are
        # terminal and do not block a later recurrence — so a DB-level UNIQUE
        # constraint would be wrong here. This index speeds the lookup.
        Index(
            "ix_insights_store_type_key",
            "store_id",
            "insight_type",
            "dedupe_key",
        ),
    )

    store_id = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Category = dashboard grouping (inventory/shelf/expiry/customer_flow/...).
    category: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    insight_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)

    # What produced it and why — always preserved.
    rule_id: Mapped[str] = mapped_column(String(80), nullable=False)
    source_modules: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    evidence: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Action + certainty
    recommended_action: Mapped[Optional[str]] = mapped_column(String(600), nullable=True)
    certainty: Mapped[str] = mapped_column(String(10), default=CERTAINTY_MEDIUM)

    # Deduplication key: f"{entity_type}:{entity_id}".
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(120), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(180), nullable=False)

    # Optional contextual FKs (informational joins, never required).
    product_id = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    shelf_id = mapped_column(
        ForeignKey("shelves.id", ondelete="SET NULL"), nullable=True, index=True
    )
    zone_id = mapped_column(
        ForeignKey("zones.id", ondelete="SET NULL"), nullable=True, index=True
    )
    camera_id = mapped_column(
        ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True, index=True
    )

    first_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    last_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    store = relationship("Store")
    product = relationship("Product")
    shelf = relationship("Shelf")
    zone = relationship("Zone")
    camera = relationship("Camera")


def default_detected_at() -> datetime:
    return datetime.now(timezone.utc)