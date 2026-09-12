"""Misplaced-product foundation (AI inference, informational only).

A product can only be flagged POSSIBLE_MISPLACEMENT when BOTH:
    1. the detected class maps to a product via the explicit `ai_classes`
       configuration, AND
    2. the shelf has an ACTIVE planogram expectation (PlanogramItem
       shelf->product) that does NOT include that product.

Unmapped classes and shelves without a planogram expectation are never
flagged — we cannot assess them. This module NEVER alters the planogram or
inventory; it only reports what the AI inferred from observations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from .shelf_intelligence import ShelfIntelligenceService, ShelfVisibleProduct


@dataclass
class MisplacementRow:
    """One (product, shelf, camera) possible-misplacement result."""

    product_id: Optional[UUID]
    product_name: Optional[str]
    sku: Optional[str]
    ai_class: str
    shelf_code: str
    zone_name: Optional[str]
    camera_id: Optional[UUID]
    camera_name: Optional[str]
    visible_count: int
    confidence: Optional[float]
    latest_observed_at: Optional[datetime] = None
    message: str = (
        "AI detected this product visibly on a shelf whose planogram expects "
        "other products. Review to confirm physical placement."
    )


class MisplacementService:
    """Flatten shelf intelligence into possible-misplacement candidates."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def misplacements(
        self,
        *,
        store_id: UUID,
        camera_id: Optional[UUID] = None,
        min_confidence: float = 0.5,
        hours: int = 24,
    ) -> List[MisplacementRow]:
        shelf_svc = ShelfIntelligenceService(self.session)
        rows: List[MisplacementRow] = []
        for shelf in shelf_svc.shelves(
            store_id=store_id,
            camera_id=camera_id,
            min_confidence=min_confidence,
            hours=hours,
        ):
            for p in shelf.visible_products:
                if not p.possible_misplacement:
                    continue
                rows.append(
                    MisplacementRow(
                        product_id=p.product_id,
                        product_name=p.product_name,
                        sku=p.sku,
                        ai_class=p.ai_class,
                        shelf_code=shelf.shelf_code,
                        zone_name=shelf.zone_name,
                        camera_id=shelf.camera_id,
                        camera_name=shelf.camera_name,
                        visible_count=p.visible_count,
                        confidence=p.confidence,
                        latest_observed_at=shelf.latest_observed_at,
                    )
                )
        rows.sort(key=lambda r: (-r.visible_count, r.shelf_code, r.ai_class.lower()))
        return rows