"""Pydantic schemas for ReconciliationResult.

Reconciliation produces INFORMATION ONLY. It never mutates inventory,
creates movements or batches, or changes stock. These schemas expose the
stored comparison result.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReconciliationRunIn(BaseModel):
    store_id: UUID
    product_ids: Optional[list[UUID]] = None
    camera_id: Optional[UUID] = None
    start: datetime
    end: datetime
    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ReconciliationResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    product_id: UUID
    camera_id: Optional[UUID]
    observation_window_start: datetime
    observation_window_end: datetime
    database_quantity: int
    ai_observed_quantity: int
    difference: int
    status: str
    confidence: Optional[float]
    details: Optional[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class ReconciliationResultList(BaseModel):
    items: list[ReconciliationResultRead]
    total: int
