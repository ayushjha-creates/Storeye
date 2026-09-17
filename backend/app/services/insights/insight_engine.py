"""InsightEngine — deterministic reconciliation + persistence (M20).

READS ONLY + INSIGHT/ALERT WRITES. This engine NEVER mutates inventory,
batches, sales, bills or movements. Its only persistence effects are:
    * `insights` rows (create / refresh / resolve / expire), and
    * M16 `alerts` rows at/above the configured actionable severity via the
      standard AlertService deduplication (never a second alert system).

CYCLE
-----
    1. Run deterministic rules against current persisted data -> candidates.
    2. Reconcile candidates with persisted OPEN/ACKNOWLEDGED insights:
         candidate key   = (insight_type, entity_type, entity_id)
         existing active with same key          -> REFRESH (evidence, severity,
                                                   last_detected_at, updated_at)
         no existing active                     -> CREATE (OPEN)
         existing active with NO matching key
             expires_at in the past             -> EXPIRED (TTL retirement)
             otherwise                          -> RESOLVED (condition cleared)
    3. Persist the categorical StoreHealth summary as a STORE_HEALTH insight
       (single cached row keyed on entity_type="store").
    4. Upsert M16 alerts for candidates whose severity is at/above
       INSIGHT_TO_ALERT_SEVERITY and whose rule declares an alert type.
    5. Commit once; roll back on any failure.

EXPIRY TTL (INSIGHT_EXPIRY_TTL_HOURS)
--------------------------------------
Rules set an explicit `expires_at` (e.g. EXPIRY_RISK on the batch expiry
date + 1 day). On the next cycle, an OPEN/ACKNOWLEDGED insight whose
`expires_at` has passed is retired to EXPIRED even if the condition is
unchanged. This keeps historical expiry insights from going stale forever;
the condition will be re-evaluated on later cycles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Insight,
    STATUS_ACKNOWLEDGED,
    STATUS_EXPIRED,
    STATUS_OPEN,
    STATUS_RESOLVED,
    INSIGHT_STORE_HEALTH,
)
from app.services.alerts import AlertService
from app.services.insights.insight_rules import (
    rule_camera_health,
    rule_customer_flow,
    rule_expiry,
    rule_high_selling_low_stock,
    rule_inventory,
    rule_low_stock_low_shelf,
    rule_shelf,
)
from app.services.insights.insight_types import RuleCandidate
from app.services.insights.store_health import (
    STORE_HEALTH_ATTENTION,
    STORE_HEALTH_CRITICAL,
    STORE_HEALTH_HEALTHY,
    StoreHealthService,
)
from .insight_rules import RuleContext


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class InsightEvalResult:
    evaluated_at: datetime = field(default_factory=_now)
    store_id: Optional[UUID] = None
    candidates: int = 0
    created: int = 0
    refreshed: int = 0
    resolved: int = 0
    expired: int = 0
    alerts_created: int = 0
    alerts_updated: int = 0
    insights: List[Insight] = field(default_factory=list)
    alerts: List[object] = field(default_factory=list)


class InsightEngine:
    """Deterministic Store Intelligence engine (see module docstring)."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # Public API — domain-scoped evaluations. All are idempotent cycles.
    # ------------------------------------------------------------------
    def evaluate(
        self,
        store_id: UUID,
        *,
        reference_date: Optional[date] = None,
        now: Optional[datetime] = None,
    ) -> InsightEvalResult:
        """Full store evaluation (all rules + store health + alert sync)."""
        ctx = RuleContext(
            self.session,
            store_id=store_id,
            now=now,
            reference_date=reference_date,
        )
        candidates: List[RuleCandidate] = []
        candidates += rule_inventory(ctx)
        candidates += rule_expiry(ctx)
        candidates += rule_shelf(ctx)
        candidates += rule_customer_flow(ctx)
        candidates += rule_camera_health(ctx)
        candidates += rule_high_selling_low_stock(ctx)
        candidates += rule_low_stock_low_shelf(ctx)

        # The categorical STORE_HEALTH summary is reconciled in the SAME cycle
        # as the rules so a single atomic evaluation persists every insight
        # (including the cached health row) and never retires sibling insights.
        health = StoreHealthService(self.session).compute(store_id, now=ctx.now)
        candidates.append(self._store_health_candidate(health))

        return self._reconcile(ctx, candidates)

    def evaluate_inventory(self, store_id: UUID, **kwargs) -> InsightEvalResult:
        ctx = self._ctx(store_id, **kwargs)
        return self._reconcile(ctx, rule_inventory(ctx))

    def evaluate_expiry(self, store_id: UUID, **kwargs) -> InsightEvalResult:
        ctx = self._ctx(store_id, **kwargs)
        return self._reconcile(ctx, rule_expiry(ctx))

    def evaluate_shelves(self, store_id: UUID, **kwargs) -> InsightEvalResult:
        ctx = self._ctx(store_id, **kwargs)
        return self._reconcile(ctx, rule_shelf(ctx))

    def evaluate_customer_flow(self, store_id: UUID, **kwargs) -> InsightEvalResult:
        ctx = self._ctx(store_id, **kwargs)
        return self._reconcile(ctx, rule_customer_flow(ctx))

    def evaluate_camera_health(self, store_id: UUID, **kwargs) -> InsightEvalResult:
        ctx = self._ctx(store_id, **kwargs)
        return self._reconcile(ctx, rule_camera_health(ctx))

    def evaluate_store_health(
        self, store_id: UUID, *, reference_date: Optional[date] = None, now: Optional[datetime] = None
    ) -> InsightEvalResult:
        """Refresh the single cached categorical STORE_HEALTH insight."""
        ctx = RuleContext(
            self.session, store_id=store_id, now=now, reference_date=reference_date
        )
        health = StoreHealthService(self.session).compute(store_id, now=ctx.now)
        candidate = self._store_health_candidate(health)
        result = self._reconcile(ctx, [candidate])
        result.store_id = store_id
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _ctx(self, store_id: UUID, **kwargs) -> RuleContext:
        return RuleContext(self.session, store_id=store_id, **kwargs)

    def _store_health_candidate(self, health) -> RuleCandidate:
        severity = {
            STORE_HEALTH_CRITICAL: "HIGH",
            STORE_HEALTH_ATTENTION: "MEDIUM",
            STORE_HEALTH_HEALTHY: "INFO",
        }[health.state]
        return RuleCandidate(
            insight_type=INSIGHT_STORE_HEALTH,
            entity_type="store",
            entity_id="store",
            severity=severity,
            title=f"Store health: {health.state}",
            description=" ".join(health.basis),
            rule_id="store_health.state",
            source_modules=["store_health"],
            recommended_action=(
                "CRITICAL: restock out-of-stock items, remove expired batches, "
                "and restore cameras immediately."
                if health.state == STORE_HEALTH_CRITICAL
                else "ATTENTION: review medium-severity insights and prioritize "
                "replenishment / expiry rotation."
                if health.state == STORE_HEALTH_ATTENTION
                else "HEALTHY: no action required — keep current routines."
            ),
            certainty="MEDIUM",
            evidence=health.to_evidence(),
        )

    def _reconcile(
        self, ctx: RuleContext, candidates: List[RuleCandidate]
    ) -> InsightEvalResult:
        now = ctx.now
        store_id = ctx.store_id
        result = InsightEvalResult(store_id=store_id, evaluated_at=now)

        try:
            active = self._load_active(store_id)
            by_key = {
                (i.insight_type, i.dedupe_key): i
                for i in active
                if (i.insight_type, i.dedupe_key)
            }
            matched: set = set()

            for cand in candidates:
                key = (cand.insight_type, cand.dedupe_key)
                existing = by_key.get(key)
                if existing is not None:
                    self._refresh(existing, cand, now)
                    result.refreshed += 1
                    matched.add(key)
                else:
                    self.session.add(self._build(cand, store_id, now))
                    result.created += 1
                    matched.add(key)
                result.candidates += 1

            # Retire active insights whose condition no longer holds.
            for (key, existing) in by_key.items():
                if key in matched:
                    continue
                if existing.expires_at is not None and existing.expires_at < now:
                    existing.status = STATUS_EXPIRED
                    existing.expired_at = now
                    existing.updated_at = now
                    result.expired += 1
                else:
                    existing.status = STATUS_RESOLVED
                    existing.resolved_at = now
                    existing.updated_at = now
                    result.resolved += 1

            # M16 alert sync (only at/above configured actionable severity).
            self._sync_alerts(ctx, result, candidates, now)

            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        # Refresh the returned list for callers.
        result.insights = list(
            self.session.scalars(select(Insight).where(Insight.store_id == store_id))
        )
        return result

    def _load_active(self, store_id: UUID) -> List[Insight]:
        return list(
            self.session.scalars(
                select(Insight).where(
                    Insight.store_id == store_id,
                    Insight.status.in_([STATUS_OPEN, STATUS_ACKNOWLEDGED]),
                )
            )
        )

    @staticmethod
    def _build(cand: RuleCandidate, store_id: UUID, now: datetime) -> Insight:
        return Insight(
            store_id=store_id,
            category=cand.category,
            insight_type=cand.insight_type,
            severity=cand.severity,
            status=STATUS_OPEN,
            title=cand.title,
            description=cand.description,
            rule_id=cand.rule_id,
            source_modules=cand.source_modules,
            evidence=cand.evidence,
            recommended_action=cand.recommended_action,
            certainty=cand.certainty,
            entity_type=cand.entity_type,
            entity_id=cand.entity_id,
            dedupe_key=cand.dedupe_key,
            product_id=cand.product_id,
            shelf_id=cand.shelf_id,
            zone_id=cand.zone_id,
            camera_id=cand.camera_id,
            first_detected_at=now,
            last_detected_at=now,
            expires_at=cand.expires_at,
        )

    @staticmethod
    def _refresh(existing: Insight, cand: RuleCandidate, now: datetime) -> None:
        existing.category = cand.category
        existing.severity = cand.severity
        existing.title = cand.title
        existing.description = cand.description
        existing.rule_id = cand.rule_id
        existing.source_modules = cand.source_modules
        existing.evidence = cand.evidence
        existing.recommended_action = cand.recommended_action
        existing.certainty = cand.certainty
        existing.expires_at = cand.expires_at
        existing.product_id = cand.product_id
        existing.shelf_id = cand.shelf_id
        existing.zone_id = cand.zone_id
        existing.camera_id = cand.camera_id
        existing.last_detected_at = now
        existing.updated_at = now

    def _sync_alerts(
        self,
        ctx: RuleContext,
        result: InsightEvalResult,
        candidates: List[RuleCandidate],
        now: datetime,
    ) -> None:
        """Upsert M16 alerts for candidates at/above the actionable severity.

        Reuses AlertService deduplication so repeated evaluations never create
        duplicate alerts. Source data is the insight's evidence (no re-run).
        """
        min_sev = str(self._settings.INSIGHT_TO_ALERT_SEVERITY).upper()
        rank = {"INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}.get(min_sev, 3)
        if rank < 2:  # never lower than MEDIUM
            rank = 2
        severity_rank = {"INFO": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}

        svc = AlertService(self.session)
        for cand in candidates:
            if not cand.alert_type:
                continue
            if severity_rank.get(cand.severity, 0) < rank:
                continue
            alert, created = svc._upsert_alert(
                store_id=ctx.store_id,
                alert_type=cand.alert_type,
                severity=cand.severity,
                title=cand.title,
                message=cand.description,
                camera_id=cand.camera_id,
                product_id=cand.product_id,
                shelf_id=cand.shelf_id,
                confidence=None,
                source_type="insights",
                source_id=cand.dedupe_key,
                detected_at=now,
                details={"insight_evidence": cand.evidence, "rule": cand.rule_id},
            )
            if created:
                result.alerts_created += 1
            else:
                result.alerts_updated += 1
            result.alerts.append(alert)