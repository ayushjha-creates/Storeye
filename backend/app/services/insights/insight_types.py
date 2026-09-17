"""Shared types + metadata for the M20 Store Intelligence engine.

Everything in this package is DETERMINISTIC and RULE-BASED:
    * an insight is an evidence-backed operational suggestion derived from
      existing persisted data (inventory, batches, shelf/product intelligence,
      alerts, anonymous journeys),
    * the engine never runs a new CV pipeline and never mutates inventory,
      batches, sales, bills or movements,
    * people flow (journey analytics) is never translated into purchase intent
      ("this customer wants X" is banned).

A RuleCandidate is a *proposed* insight for one (store, type, entity). The
engine reconciles candidates against existing insights using the documented
dedup + lifecycle rules (see ../models/insight.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from app.models.insight import (
    CATEGORY_CAMERA,
    CATEGORY_CUSTOMER_FLOW,
    CATEGORY_EXPIRY,
    CATEGORY_INVENTORY,
    CATEGORY_SHELF,
    CATEGORY_STORE_HEALTH,
    CERTAINTY_HIGH,
    CERTAINTY_LOW,
    CERTAINTY_MEDIUM,
    INSIGHT_CAMERA_HEALTH,
    INSIGHT_EXPIRED_BATCH,
    INSIGHT_EXPIRY_RISK,
    INSIGHT_HIGH_DWELL_ZONE,
    INSIGHT_HIGH_SELLING_LOW_STOCK,
    INSIGHT_HIGH_TRAFFIC_LOW_SHELF,
    INSIGHT_HIGH_TRAFFIC_ZONE,
    INSIGHT_INVENTORY_RISK,
    INSIGHT_LOW_SHELF_AVAILABILITY,
    INSIGHT_LOW_STOCK,
    INSIGHT_LOW_STOCK_LOW_SHELF,
    INSIGHT_MISPLACEMENT,
    INSIGHT_OUT_OF_STOCK,
    INSIGHT_STOCK_ROTATION,
    INSIGHT_STORE_HEALTH,
    SEV_HIGH,
    SEV_INFO,
    SEV_LOW,
    SEV_MEDIUM,
)


# ---------------------------------------------------------------------------
# Deterministic metadata: category + default severity per insight type.
# ---------------------------------------------------------------------------
TYPE_CATEGORY: dict = {
    INSIGHT_LOW_STOCK: CATEGORY_INVENTORY,
    INSIGHT_OUT_OF_STOCK: CATEGORY_INVENTORY,
    INSIGHT_LOW_STOCK_LOW_SHELF: CATEGORY_INVENTORY,
    INSIGHT_HIGH_SELLING_LOW_STOCK: CATEGORY_INVENTORY,
    INSIGHT_INVENTORY_RISK: CATEGORY_INVENTORY,
    INSIGHT_EXPIRY_RISK: CATEGORY_EXPIRY,
    INSIGHT_EXPIRED_BATCH: CATEGORY_EXPIRY,
    INSIGHT_STOCK_ROTATION: CATEGORY_EXPIRY,
    INSIGHT_LOW_SHELF_AVAILABILITY: CATEGORY_SHELF,
    INSIGHT_MISPLACEMENT: CATEGORY_SHELF,
    INSIGHT_HIGH_TRAFFIC_ZONE: CATEGORY_CUSTOMER_FLOW,
    INSIGHT_HIGH_DWELL_ZONE: CATEGORY_CUSTOMER_FLOW,
    INSIGHT_HIGH_TRAFFIC_LOW_SHELF: CATEGORY_CUSTOMER_FLOW,
    INSIGHT_CAMERA_HEALTH: CATEGORY_CAMERA,
    INSIGHT_STORE_HEALTH: CATEGORY_STORE_HEALTH,
}

# Default severity each rule assigns. Reflects business impact, NOT evidence
# strength (evidence strength is the separate `certainty`).
TYPE_DEFAULT_SEVERITY: dict = {
    INSIGHT_LOW_STOCK: SEV_MEDIUM,
    INSIGHT_OUT_OF_STOCK: SEV_HIGH,
    INSIGHT_LOW_STOCK_LOW_SHELF: SEV_MEDIUM,
    INSIGHT_HIGH_SELLING_LOW_STOCK: SEV_MEDIUM,
    INSIGHT_INVENTORY_RISK: SEV_MEDIUM,
    INSIGHT_EXPIRY_RISK: SEV_MEDIUM,
    INSIGHT_EXPIRED_BATCH: SEV_HIGH,
    INSIGHT_STOCK_ROTATION: SEV_LOW,
    INSIGHT_LOW_SHELF_AVAILABILITY: SEV_MEDIUM,
    INSIGHT_MISPLACEMENT: SEV_LOW,
    INSIGHT_HIGH_TRAFFIC_ZONE: SEV_INFO,
    INSIGHT_HIGH_DWELL_ZONE: SEV_INFO,
    INSIGHT_HIGH_TRAFFIC_LOW_SHELF: SEV_MEDIUM,
    INSIGHT_CAMERA_HEALTH: SEV_HIGH,
    INSIGHT_STORE_HEALTH: SEV_INFO,
}

SEVERITY_RANK = {SEV_INFO: 0, SEV_LOW: 1, SEV_MEDIUM: 2, SEV_HIGH: 3}


@dataclass
class RuleCandidate:
    """A single deterministic insight proposal for one (store-as-input, type,
    entity). entity_id is an opaque string forming the dedupe key with
    entity_type; the contextual FKs (product/shelf/zone/camera) are optional
    informational links only."""

    insight_type: str
    entity_type: str  # product | shelf | zone | camera | batch | store
    entity_id: str
    severity: str
    title: str
    description: str
    rule_id: str
    source_modules: List[str]
    recommended_action: str
    certainty: str = CERTAINTY_MEDIUM
    product_id: Optional[UUID] = None
    shelf_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    camera_id: Optional[UUID] = None
    expires_at: Optional[datetime] = None
    # evidence dict prepared by the rule (embedded per rule, never opaque).
    evidence: dict = field(default_factory=dict)
    # Optional M16 alert integration (== None means "do not raise an alert").
    alert_type: Optional[str] = None

    @property
    def dedupe_key(self) -> str:
        return f"{self.entity_type}:{self.entity_id}"

    @property
    def category(self) -> str:
        return TYPE_CATEGORY.get(self.insight_type, CATEGORY_INVENTORY)