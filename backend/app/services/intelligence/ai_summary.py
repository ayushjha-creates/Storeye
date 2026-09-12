"""Store AI summary — a dashboard-level digest of what the Edge AI is seeing.

Collapses the derived product/shelf/misplacement services plus reconciliation
results into one read-only snapshot. Every value is clearly informational AI
state; any notion of a "shortage" carries the POSSIBLE_/camera-scoped prefix
from the underlying services (see the module docstrings there). Nothing here
mutates inventory, batches, bills or sales.

`ai_running` = cameras that produced at least one observation in the window.
This is an honest proxy for "pipeline is running and seeing something", NOT a
hardware/process health check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Camera,
    Observation,
    OBS_PERSON,
    REC_REVIEW,
    REC_SHORTAGE,
    REC_SURPLUS,
    ReconciliationResult,
)

from .misplacement import MisplacementService
from .product_intelligence import ProductIntelligenceService
from .shelf_intelligence import (
    SHELF_STATE_EMPTY,
    SHELF_STATE_LOW,
    SHELF_STATE_NORMAL,
    SHELF_STATE_UNKNOWN,
    ShelfIntelligenceService,
    parse_shelf_regions,
)


@dataclass
class CameraSummary:
    total: int = 0
    active: int = 0
    ai_running: int = 0
    ai_stopped: int = 0  # active but with NO observation in the window
    regions_configured: int = 0


@dataclass
class PeopleSummary:
    distinct_tracks: int = 0
    last_observed_at: Optional[datetime] = None


@dataclass
class ProductSummary:
    visible_classes: int = 0
    mapped_classes: int = 0
    unmapped_classes: int = 0
    total_visible_quantity: int = 0


@dataclass
class ShelfSummary:
    regions_configured: int = 0
    with_ai_data: int = 0
    empty_visible: int = 0
    low_visible: int = 0
    normal_visible: int = 0
    unknown: int = 0
    possible_misplacements: int = 0


@dataclass
class ReconciliationSummary:
    possible_shortages: int = 0
    possible_surpluses: int = 0
    review_required: int = 0
    total_last_window: int = 0


@dataclass
class AISummary:
    computed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    window_hours: int = 24
    cameras: CameraSummary = field(default_factory=CameraSummary)
    people: PeopleSummary = field(default_factory=PeopleSummary)
    products: ProductSummary = field(default_factory=ProductSummary)
    shelves: ShelfSummary = field(default_factory=ShelfSummary)
    reconciliation: ReconciliationSummary = field(default_factory=ReconciliationSummary)


class AISummaryService:
    """Build the store AI digest (read-only)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def summary(self, *, store_id: UUID, hours: int = 24) -> AISummary:
        window = min(max(int(hours), 1), 24 * 7)
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=window)
        out = AISummary(window_hours=window)

        cameras = list(
            self.session.scalars(
                select(Camera).where(Camera.store_id == store_id).order_by(Camera.name)
            )
        )
        out.cameras.total = len(cameras)
        active = [c for c in cameras if c.is_active]
        out.cameras.active = len(active)
        out.cameras.regions_configured = sum(
            1 for c in cameras if parse_shelf_regions(c)
        )

        # Camera AI activity = produced at least one observation in window.
        observed_cameras = set(
            self.session.scalars(
                select(Observation.camera_id)
                .where(
                    Observation.store_id == store_id,
                    Observation.camera_id.is_not(None),
                    Observation.observed_at >= start,
                    Observation.observed_at <= end,
                )
                .distinct()
            )
        )
        out.cameras.ai_running = sum(1 for c in active if c.id in observed_cameras)
        out.cameras.ai_stopped = out.cameras.active - out.cameras.ai_running

        # People (anonymous session-scoped tracks only).
        people_stmt = self.session.execute(
            select(
                func.max(Observation.observed_at),
                func.count(func.distinct(Observation.track_id)),
            ).where(
                Observation.store_id == store_id,
                Observation.observation_type == OBS_PERSON,
                Observation.track_id.is_not(None),
                Observation.observed_at >= start,
                Observation.observed_at <= end,
            )
        )
        track_rows = people_stmt.first()
        if track_rows:
            out.people.last_observed_at = track_rows[0]
            out.people.distinct_tracks = int(track_rows[1] or 0)

        # Product + shelf intelligence (reuse the same derived services).
        product_rows = ProductIntelligenceService(self.session).products(
            store_id=store_id, min_confidence=0.5, hours=window
        )
        out.products.visible_classes = len(product_rows)
        out.products.mapped_classes = sum(1 for r in product_rows if r.mapped)
        out.products.unmapped_classes = len(product_rows) - out.products.mapped_classes
        out.products.total_visible_quantity = sum(r.visible_count for r in product_rows)

        shelf_rows = ShelfIntelligenceService(self.session).shelves(
            store_id=store_id, min_confidence=0.5, hours=window
        )
        out.shelves.regions_configured = len(shelf_rows)
        for r in shelf_rows:
            if r.detection_status == SHELF_STATE_UNKNOWN:
                out.shelves.unknown += 1
            else:
                out.shelves.with_ai_data += 1
            if r.detection_status == SHELF_STATE_EMPTY:
                out.shelves.empty_visible += 1
            elif r.detection_status == SHELF_STATE_LOW:
                out.shelves.low_visible += 1
            elif r.detection_status == SHELF_STATE_NORMAL:
                out.shelves.normal_visible += 1
        out.shelves.possible_misplacements = len(
            MisplacementService(self.session).misplacements(
                store_id=store_id, min_confidence=0.5, hours=window
            )
        )

        # Persisted reconciliation results within the same window.
        rec_rows = list(
            self.session.scalars(
                select(ReconciliationResult).where(
                    ReconciliationResult.store_id == store_id,
                    ReconciliationResult.observation_window_end >= start,
                    ReconciliationResult.observation_window_start <= end,
                )
            )
        )
        out.reconciliation.total_last_window = len(rec_rows)
        out.reconciliation.possible_shortages = sum(
            1 for r in rec_rows if r.status == REC_SHORTAGE
        )
        out.reconciliation.possible_surpluses = sum(
            1 for r in rec_rows if r.status == REC_SURPLUS
        )
        out.reconciliation.review_required = sum(
            1 for r in rec_rows if r.status == REC_REVIEW
        )
        return out