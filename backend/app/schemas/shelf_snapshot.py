"""M30 periodic shelf-occupancy snapshot API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ShelfSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    camera_id: Optional[UUID] = None
    shelf_code: str
    shelf_label: Optional[str] = None
    region_bbox: Optional[list] = None
    snapshot_path: Optional[str] = None
    crop_path: Optional[str] = None
    has_image: bool = False
    fill_percentage: float
    status: str
    product_count: int
    occluded: bool
    occlusion_note: Optional[str] = None
    confidence: Optional[float] = None
    observed_at: datetime
    created_at: Optional[datetime] = None


class ShelfSnapshotListRead(BaseModel):
    items: list[ShelfSnapshotRead] = Field(default_factory=list)
    total: int = 0


class ShelfStatusCounts(BaseModel):
    """Per-status tallies for a camera's shelf summary card."""

    EMPTY: int = 0
    LOW: int = 0
    MEDIUM: int = 0
    FULL: int = 0
    OCCLUDED: int = 0


class ShelfSnapshotSummaryRead(BaseModel):
    """Latest snapshot PER configured region (the shelf-monitor card payload)."""

    items: list[ShelfSnapshotRead] = Field(default_factory=list)
    status: ShelfStatusCounts = Field(default_factory=ShelfStatusCounts)
    total_regions: int = 0
    last_scan_at: Optional[datetime] = None


class ShelfHistoryRead(BaseModel):
    """One shelf's recent snapshot history (for sparklines / trend)."""

    shelf_code: str
    camera_id: Optional[UUID] = None
    items: list[ShelfSnapshotRead] = Field(default_factory=list)
    total: int = 0