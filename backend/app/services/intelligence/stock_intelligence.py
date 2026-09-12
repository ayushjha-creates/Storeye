"""Stock discrepancy intelligence.

Surfaces M9 ReconciliationResult entries as readable discrepancy insights:
MATCH, POSSIBLE_SHORTAGE, POSSIBLE_SURPLUS, REVIEW_REQUIRED.

A reconciliation result is EVIDENCE, not a transaction — this service only
reads ReconciliationResult rows and returns derived structures. It never
modifies inventory, batches, movements, or the results themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ReconciliationResult, Product, REC_MATCH, REC_REVIEW


@dataclass
class DiscrepancyInsight:
    """A single reconciliation outcome as an insight. Derived, not persisted."""

    reconciliation_id: UUID
    store_id: UUID
    product_id: UUID
    sku: str
    name: str
    camera_id: Optional[UUID]
    window_start: datetime
    window_end: datetime
    database_quantity: int
    ai_observed_quantity: int
    difference: int
    status: str
    confidence: Optional[float]
    counting_rule: Optional[str]

    @property
    def is_ok(self) -> bool:
        return self.status == REC_MATCH

    @property
    def review_required(self) -> bool:
        return self.status == REC_REVIEW


class StockDiscrepancyIntelligence:
    def __init__(self, session: Session) -> None:
        self.session = session

    def results(self, store_id: UUID) -> List[DiscrepancyInsight]:
        """Return all reconciliation discrepancies for a store, newest first."""
        stmt = (
            select(ReconciliationResult, Product.sku, Product.name)
            .join(Product, Product.id == ReconciliationResult.product_id)
            .where(ReconciliationResult.store_id == store_id)
            .order_by(ReconciliationResult.created_at.desc())
        )
        out: List[DiscrepancyInsight] = []
        for res, sku, name in self.session.execute(stmt):
            out.append(
                DiscrepancyInsight(
                    reconciliation_id=res.id,
                    store_id=res.store_id,
                    product_id=res.product_id,
                    sku=sku,
                    name=name,
                    camera_id=res.camera_id,
                    window_start=res.observation_window_start,
                    window_end=res.observation_window_end,
                    database_quantity=res.database_quantity,
                    ai_observed_quantity=res.ai_observed_quantity,
                    difference=res.difference,
                    status=res.status,
                    confidence=res.confidence,
                    counting_rule=(res.details or {}).get("counting_rule"),
                )
            )
        return out

    def by_status(self, store_id: UUID, status: str) -> List[DiscrepancyInsight]:
        """Discrepancies with a specific status (e.g. POSSIBLE_SHORTAGE)."""
        return [d for d in self.results(store_id) if d.status == status]

    def recent(self, store_id: UUID, limit: Optional[int] = 5) -> List[DiscrepancyInsight]:
        return self.results(store_id)[:limit]