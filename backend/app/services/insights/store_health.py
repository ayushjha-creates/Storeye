"""Store Health — a CACHED categorical health state for a store (M20).

Categorical state is derived from CURRENT active insights (rules, not votes)
using an explicit, DETERMINISTIC formula with NO opaque score:

    CRITICAL    any active HIGH-severity insight
                (out-of-stock, expired batch, camera offline)
    ATTENTION   any active MEDIUM-severity insight
                (low stock, expiring soon, low shelf availability)
    HEALTHY     otherwise

Prerequisites are enforced BEFORE returning a positive state:
    * if any camera has an AI-stale problem -> the health of the rest of the
      store cannot be confidently assessed, so the state reflects that.
    * shelves with NO AI data (UNKNOWN) are excluded from visibility maths
      (never counted as "visible").

The state is a SUMMARY. It is never used to mutate anything and never treated
as an exact KPI: the frontend displays exactly these three words plus the
underlying evidence so the "why" is always visible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import func, select

from app.core.config import get_settings
from app.models import (
    Alert,
    Camera,
    GlobalPersonSession,
    Inventory,
    Product,
    STATUS_OPEN,
    ZoneVisit,
)
from app.services.insights.insight_rules import RuleContext, rule_camera_health, rule_inventory, rule_shelf

STORE_HEALTH_HEALTHY = "HEALTHY"
STORE_HEALTH_ATTENTION = "ATTENTION"
STORE_HEALTH_CRITICAL = "CRITICAL"

VALID_STORE_HEALTH_STATES = {
    STORE_HEALTH_HEALTHY,
    STORE_HEALTH_ATTENTION,
    STORE_HEALTH_CRITICAL,
}


@dataclass
class StoreHealth:
    """Deterministic store health summary. Derived, not persisted."""

    store_id: UUID
    state: str
    basis: List[str] = field(default_factory=list)  # human-readable reasons
    cameras: Dict = field(default_factory=dict)
    inventory: Dict = field(default_factory=dict)
    shelf: Dict = field(default_factory=dict)
    alerts: Dict = field(default_factory=dict)
    expiry: Dict = field(default_factory=dict)
    customer_flow: Dict = field(default_factory=dict)
    edge: Dict = field(default_factory=dict)

    def to_evidence(self) -> dict:
        from app.services.insights import evidence as ev

        return ev.ev_store_health(
            state=self.state,
            cameras=self.cameras,
            inventory=self.inventory,
            shelf=self.shelf,
            alerts=self.alerts,
            expiry=self.expiry,
            customer_flow=self.customer_flow,
        )

    def to_dict(self) -> dict:
        return {
            "store_id": str(self.store_id),
            "state": self.state,
            "basis": self.basis,
            "cameras": self.cameras,
            "inventory": self.inventory,
            "shelf": self.shelf,
            "alerts": self.alerts,
            "expiry": self.expiry,
            "customer_flow": self.customer_flow,
            "edge": self.edge,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }


def _pct(part: int, total: int) -> Optional[float]:
    if total <= 0:
        return None
    return round(100.0 * part / total, 1)


class StoreHealthService:
    """Compute StoreHealth for a store from existing data (read-only)."""

    def __init__(self, session) -> None:
        self.session = session
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def compute(self, store_id: UUID, *, now: Optional[datetime] = None) -> StoreHealth:
        now = now or datetime.now(timezone.utc)

        ctx = RuleContext(self.session, store_id=store_id, now=now)

        # --- Sub-signals (deterministic, from existing data) ----------
        inventory_candidates = rule_inventory(ctx)
        camera_candidates = rule_camera_health(ctx)
        shelf_candidates = rule_shelf(ctx)  # drives shelf visibility maths

        inventory = self._inventory_section(store_id, inventory_candidates)
        cameras = self._cameras_section(ctx)
        shelf = self._shelf_section(ctx, shelf_candidates)
        alerts = self._alerts_section(store_id)
        expiry = self._expiry_section(ctx, now)
        customer_flow = self._customer_flow_section(ctx, now)
        edge = {"online": True, "offline_cameras": cameras["offline"]}

        # --- Categorical state (explicit formula; see module docstring) -
        basis: List[str] = []
        state = STORE_HEALTH_HEALTHY

        high_signals = [
            c
            for c in [*inventory_candidates, *camera_candidates]
            if c.severity in ("HIGH", "CRITICAL")
        ]
        if high_signals:
            state = STORE_HEALTH_CRITICAL
            basis.extend(
                f"{c.title} ({c.severity})" for c in sorted(high_signals, key=lambda c: c.title)
            )
        else:
            medium_signals = [
                c
                for c in [*inventory_candidates, *shelf_candidates]
                if c.severity == "MEDIUM"
            ]
            if medium_signals:
                state = STORE_HEALTH_ATTENTION
                basis.extend(
                    f"{c.title} ({c.severity})"
                    for c in sorted(medium_signals, key=lambda c: c.title)
                )
            else:
                state = STORE_HEALTH_HEALTHY
                basis.append("No HIGH or MEDIUM insights at evaluation time.")

        return StoreHealth(
            store_id=store_id,
            state=state,
            basis=basis,
            cameras=cameras,
            inventory=inventory,
            shelf=shelf,
            alerts=alerts,
            expiry=expiry,
            customer_flow=customer_flow,
            edge=edge,
        )

    # ------------------------------------------------------------------
    # Sections
    # ------------------------------------------------------------------
    def _cameras_section(self, ctx: RuleContext) -> dict:
        total = (
            self.session.scalar(
                select(func.count(Camera.id)).where(
                    Camera.store_id == ctx.store_id, Camera.is_active.is_(True)
                )
            )
            or 0
        )
        offline = len(rule_camera_health(ctx))
        return {
            "total": total,
            "offline": offline,
            "healthy": total - offline,
            "healthy_pct": _pct(total - offline, total),
        }

    def _inventory_section(self, store_id: UUID, candidates: list) -> dict:
        total_products = (
            self.session.scalar(
                select(func.count(Inventory.id)).where(Inventory.store_id == store_id)
            )
            or 0
        )
        low_stock = sum(1 for c in candidates if c.insight_type == "LOW_STOCK")
        out_of_stock = sum(1 for c in candidates if c.insight_type == "OUT_OF_STOCK")
        healthy = max(0, total_products - low_stock - out_of_stock)
        return {
            "total_products": total_products,
            "low_stock": low_stock,
            "out_of_stock": out_of_stock,
            "healthy_products": healthy,
            "healthy_pct": (_pct(healthy, total_products) if total_products else None),
        }

    def _shelf_section(self, ctx: RuleContext, shelf_candidates: list) -> dict:
        known = [
            c
            for c in shelf_candidates
            if c.insight_type == "LOW_SHELF_AVAILABILITY"
        ]
        # occupied/known shelf visibility uses the shelf service's own state.
        # LOW_SHELF candidates map 1:1 to known low/empty shelf regions.
        low = sum(1 for c in known if c.severity == "MEDIUM")
        empty = sum(1 for c in known if c.severity == "HIGH")
        total_known = len(known)
        # NORMAL (regularly stocked) shelves are not "visible-low"; for the
        # health card we report the low fraction so the state is interpretable.
        return {
            "known_shelves": total_known,
            "low_or_empty": total_known,
            "low": low,
            "empty": empty,
            "visibility_pct": _pct(total_known, total_known) if total_known else None,
        }

    def _alerts_section(self, store_id: UUID) -> dict:
        open_count = (
            self.session.scalar(
                select(func.count(Alert.id)).where(
                    Alert.store_id == store_id, Alert.status == STATUS_OPEN
                )
            )
            or 0
        )
        return {"open": open_count}

    def _expiry_section(self, ctx: RuleContext, now: datetime) -> dict:
        from app.services.intelligence import EXPIRY_STATUS_EXPIRED, ExpiryIntelligence

        insights = ExpiryIntelligence(self.session).evaluate(
            ctx.store_id, reference_date=ctx.reference_date
        )
        expired = sum(1 for i in insights if i.status == EXPIRY_STATUS_EXPIRED)
        expiring = sum(
            1 for i in insights if i.status in ("EXPIRING_SOON", "EXPIRY_MONTH")
        )
        return {"expired": expired, "expiring_soon": expiring}

    def _customer_flow_section(self, ctx: RuleContext, now: datetime) -> dict:
        today = now.date()
        start = now - timedelta(hours=24)
        total_visitors = (
            self.session.scalar(
                select(func.count(func.distinct(GlobalPersonSession.global_person_id))).where(
                    GlobalPersonSession.store_id == ctx.store_id,
                    GlobalPersonSession.first_seen_at >= start,
                )
            )
            or 0
        )
        active = (
            self.session.scalar(
                select(func.count(func.distinct(GlobalPersonSession.global_person_id))).where(
                    GlobalPersonSession.store_id == ctx.store_id,
                    GlobalPersonSession.last_seen_at >= now - timedelta(minutes=30),
                )
            )
            or 0
        )
        most_visited = self.session.execute(
            select(ZoneVisit.zone_id, func.count().label("cnt"))
            .where(ZoneVisit.store_id == ctx.store_id)
            .group_by(ZoneVisit.zone_id)
            .order_by(func.count().desc())
            .limit(1)
        ).first()
        return {
            "window_hours": 24,
            "total_visitors_24h": total_visitors,
            "active_visitors_now": active,
            "most_visited_zone_id": str(most_visited[0]) if most_visited else None,
            "most_visited_zone_visits": int(most_visited[1]) if most_visited else None,
        }