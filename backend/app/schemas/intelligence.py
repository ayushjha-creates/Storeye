"""Pydantic response schemas for Storeye Product/Shelf Intelligence.

These mirror the derived, read-only dataclasses in
app.services.intelligence. None of the models below can mutate business
state — they are pure AI-observation digests.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ShelfVisibleProductRead(BaseModel):
    """One AI class/product visible in a shelf region."""

    model_config = ConfigDict(from_attributes=True)

    ai_class: str
    product_id: Optional[UUID] = None
    product_name: Optional[str] = None
    sku: Optional[str] = None
    visible_count: int
    confidence: Optional[float] = None
    counting_rule: str
    expected_on_shelf: Optional[bool] = None
    possible_misplacement: bool = False


class ShelfIntelligenceRead(BaseModel):
    """One (configured shelf region, camera) AI-intelligence result."""

    model_config = ConfigDict(from_attributes=True)

    shelf_code: str
    region_label: Optional[str] = None
    shelf_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    zone_name: Optional[str] = None
    camera_id: Optional[UUID] = None
    camera_name: Optional[str] = None
    bbox: List[float]
    detection_status: str
    estimated_visible_occupancy: Optional[float] = None
    occupied_pct: Optional[float] = None
    visible_products: List[ShelfVisibleProductRead] = []
    latest_observed_at: Optional[datetime] = None
    mean_confidence: Optional[float] = None
    last_analysis_message: Optional[str] = None
    occupancy_method: Optional[str] = None
    occupancy_samples: Optional[int] = None
    refill_recommended: bool = False


class ShelfIntelligenceList(BaseModel):
    items: List[ShelfIntelligenceRead]
    total: int


class ProductIntelligenceRead(BaseModel):
    """One (AI class, camera) product-intelligence result."""

    model_config = ConfigDict(from_attributes=True)

    ai_class: str
    mapped: bool
    product_id: Optional[UUID] = None
    product_name: Optional[str] = None
    sku: Optional[str] = None
    camera_id: Optional[UUID] = None
    camera_name: Optional[str] = None
    shelf_code: Optional[str] = None
    visible_count: int
    confidence: Optional[float] = None
    counting_rule: str
    latest_observed_at: Optional[datetime] = None
    database_quantity: Optional[int] = None
    difference: Optional[int] = None
    comparison_status: str
    message: Optional[str] = None


class ProductIntelligenceList(BaseModel):
    items: List[ProductIntelligenceRead]
    total: int


class ProductCandidateRead(BaseModel):
    """PRODUCT_CANDIDATE: a detected AI class not mapped to any catalog product.

    Read-only and never guessed — the operator decides the mapping.
    """

    ai_class: str
    visible_count: int
    confidence: Optional[float] = None
    camera_id: Optional[UUID] = None
    camera_name: Optional[str] = None
    shelf_code: Optional[str] = None
    latest_observed_at: Optional[datetime] = None
    counting_rule: str
    message: str


class ProductCandidateList(BaseModel):
    items: List[ProductCandidateRead]
    total: int


class MisplacementRead(BaseModel):
    """One (product, shelf, camera) possible-misplacement result."""

    model_config = ConfigDict(from_attributes=True)

    product_id: Optional[UUID] = None
    product_name: Optional[str] = None
    sku: Optional[str] = None
    ai_class: str
    shelf_code: str
    zone_name: Optional[str] = None
    camera_id: Optional[UUID] = None
    camera_name: Optional[str] = None
    visible_count: int
    confidence: Optional[float] = None
    latest_observed_at: Optional[datetime] = None
    message: str


class MisplacementList(BaseModel):
    items: List[MisplacementRead]
    total: int


class CameraSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total: int = 0
    active: int = 0
    ai_running: int = 0
    ai_stopped: int = 0
    regions_configured: int = 0


class PeopleSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    distinct_tracks: int = 0
    last_observed_at: Optional[datetime] = None


class ProductSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    visible_classes: int = 0
    mapped_classes: int = 0
    unmapped_classes: int = 0
    total_visible_quantity: int = 0


class ShelfSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    regions_configured: int = 0
    with_ai_data: int = 0
    empty_visible: int = 0
    low_visible: int = 0
    normal_visible: int = 0
    unknown: int = 0
    possible_misplacements: int = 0


class ReconciliationSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    possible_shortages: int = 0
    possible_surpluses: int = 0
    review_required: int = 0
    total_last_window: int = 0


class AISummaryRead(BaseModel):
    """Whole-store AI digest. Every value is informational."""

    model_config = ConfigDict(from_attributes=True)

    computed_at: datetime
    window_hours: int
    cameras: CameraSummaryRead
    people: PeopleSummaryRead
    products: ProductSummaryRead
    shelves: ShelfSummaryRead
    reconciliation: ReconciliationSummaryRead