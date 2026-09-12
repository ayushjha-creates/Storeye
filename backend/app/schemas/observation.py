"""Pydantic schemas for AI Observation.

Architectural rule: recording an observation NEVER changes inventory or
creates batches. These schemas are purely for persisting/reporting what the
store "saw".
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ObservationCreate(BaseModel):
    observation_type: str = Field(..., max_length=40)
    store_id: Optional[UUID] = None
    camera_id: Optional[UUID] = None
    product_id: Optional[UUID] = None
    batch_id: Optional[UUID] = None
    track_id: Optional[int] = None
    frame_number: Optional[int] = None
    source: Optional[str] = Field(default=None, max_length=500)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    bbox: Optional[list[float]] = None
    text: Optional[str] = None
    source_observation_id: Optional[UUID] = None
    observed_at: Optional[datetime] = None
    details: Optional[dict[str, Any]] = None


class ObservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    observation_type: str
    store_id: Optional[UUID]
    camera_id: Optional[UUID]
    product_id: Optional[UUID]
    batch_id: Optional[UUID]
    track_id: Optional[int]
    frame_number: Optional[int]
    source: Optional[str]
    confidence: Optional[float]
    bbox: Optional[list[float]]
    text: Optional[str]
    source_observation_id: Optional[UUID]
    observed_at: datetime
    details: Optional[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class ObservationList(BaseModel):
    items: list[ObservationRead]
    total: int


class ActivityBucket(BaseModel):
    bucket_ts: datetime
    count: int


class ObservationSummary(BaseModel):
    total: int
    by_type: dict[str, int]
    distinct_tracks: int
    avg_confidence: Optional[float]
    last_observed_at: Optional[datetime]
    activity: list[ActivityBucket]
