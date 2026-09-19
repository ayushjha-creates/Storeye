"""Storeye Product & Shelf Intelligence API routes.

M15 — Product & Shelf Intelligence.

Everything here is a PURE READ digest derived from real Edge AI observations.
These endpoints never mutate inventory, batches, bills or sales.

RULES
-----
- "Visible quantity" = AI-observed, camera-scoped (see counting module).
- "Database quantity" = recorded inventory (business truth), shown for
  comparison ONLY. Never auto-reconciled.
- "Unmapped AI class" = a detected shelf class not tied to any product via
  `products.ai_classes`. Never silently guessed.
- Shelf states are EMPTY_VISIBLE / LOW_VISIBLE / NORMAL_VISIBLE / UNKNOWN —
  never "out of stock".
"""

from __future__ import annotations

from typing import Optional

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..authz import require_same_store
from ..deps import get_db, require_role
from ...models import Store, User
from ...schemas import (
    AISummaryRead,
    MisplacementList,
    MisplacementRead,
    ProductCandidateList,
    ProductCandidateRead,
    ProductIntelligenceList,
    ProductIntelligenceRead,
    ShelfIntelligenceList,
    ShelfIntelligenceRead,
)
from ...services.intelligence import (
    AISummaryService,
    MisplacementService,
    ProductIntelligenceService,
    ShelfIntelligenceService,
)

router = APIRouter(prefix="/intelligence", tags=["intelligence"])


def _require_store(db: Session, current_user: User, store_id: UUID) -> None:
    require_same_store(current_user, store_id)
    if db.get(Store, store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")


def _window_hours(hours: int) -> int:
    return min(max(int(hours), 1), 24 * 7)


@router.get("/products", response_model=ProductIntelligenceList)
def list_product_intelligence(
    store_id: UUID,
    camera_id: Optional[UUID] = None,
    product_id: Optional[UUID] = None,
    class_name: Optional[str] = Query(
        default=None,
        description="Restrict to one AI class label (details.class_name)",
    ),
    min_confidence: float = Query(
        default=0.5, ge=0.0, le=1.0, description="Ignore detections below this confidence"
    ),
    hours: int = Query(default=24, ge=1, le=168, description="Look-back window"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    """Product intelligence: AI-visible (class/product, camera) rows with the
    comparison against recorded inventory. Read-only."""
    _require_store(db, current_user, store_id)
    rows = ProductIntelligenceService(db).products(
        store_id=store_id,
        camera_id=camera_id,
        product_id=product_id,
        class_name=class_name,
        min_confidence=min_confidence,
        hours=_window_hours(hours),
    )
    return ProductIntelligenceList(
        items=[ProductIntelligenceRead.model_validate(r) for r in rows],
        total=len(rows),
    )


@router.get("/product-candidates", response_model=ProductCandidateList)
def list_product_candidates(
    store_id: UUID,
    camera_id: Optional[UUID] = None,
    min_confidence: float = Query(
        default=0.5, ge=0.0, le=1.0, description="Ignore detections below this confidence"
    ),
    hours: int = Query(default=24, ge=1, le=168, description="Look-back window"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    """PRODUCT_CANDIDATE path: real detections whose AI class is not mapped to
    any catalog product. Read-only — the operator maps them; nothing is guessed."""
    _require_store(db, current_user, store_id)
    rows = ProductIntelligenceService(db).candidates(
        store_id=store_id,
        camera_id=camera_id,
        min_confidence=min_confidence,
        hours=_window_hours(hours),
    )
    return ProductCandidateList(
        items=[
            ProductCandidateRead(
                ai_class=r.ai_class,
                visible_count=r.visible_count,
                confidence=r.confidence,
                camera_id=r.camera_id,
                camera_name=r.camera_name,
                shelf_code=r.shelf_code,
                latest_observed_at=r.latest_observed_at,
                counting_rule=r.counting_rule,
                message=r.message or "",
            )
            for r in rows
        ],
        total=len(rows),
    )


@router.get("/shelves", response_model=ShelfIntelligenceList)
def list_shelf_intelligence(
    store_id: UUID,
    camera_id: Optional[UUID] = None,
    min_confidence: float = Query(
        default=0.5, ge=0.0, le=1.0, description="Ignore detections below this confidence"
    ),
    hours: int = Query(default=24, ge=1, le=168, description="Look-back window"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    """Shelf intelligence: per (configured shelf region, camera) visible
    occupancy, state and detected products. Read-only."""
    _require_store(db, current_user, store_id)
    rows = ShelfIntelligenceService(db).shelves(
        store_id=store_id,
        camera_id=camera_id,
        min_confidence=min_confidence,
        hours=_window_hours(hours),
    )
    return ShelfIntelligenceList(
        items=[ShelfIntelligenceRead.model_validate(r) for r in rows],
        total=len(rows),
    )


@router.get("/misplacements", response_model=MisplacementList)
def list_misplacements(
    store_id: UUID,
    camera_id: Optional[UUID] = None,
    min_confidence: float = Query(
        default=0.5, ge=0.0, le=1.0, description="Ignore detections below this confidence"
    ),
    hours: int = Query(default=24, ge=1, le=168, description="Look-back window"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    """Possible misplaced products: mapped product detected on a shelf with an
    active planogram expectation that excludes it. Informational only."""
    _require_store(db, current_user, store_id)
    rows = MisplacementService(db).misplacements(
        store_id=store_id,
        camera_id=camera_id,
        min_confidence=min_confidence,
        hours=_window_hours(hours),
    )
    return MisplacementList(
        items=[MisplacementRead.model_validate(r) for r in rows],
        total=len(rows),
    )


@router.get("/summary", response_model=AISummaryRead)
def get_ai_summary(
    store_id: UUID,
    hours: int = Query(default=24, ge=1, le=168, description="Look-back window"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    """Store AI digest: cameras running, people, products, shelves, and
    possible shortages/surpluses from the last reconciliation run. Read-only."""
    _require_store(db, current_user, store_id)
    return AISummaryService(db).summary(
        store_id=store_id,
        hours=_window_hours(hours),
    )