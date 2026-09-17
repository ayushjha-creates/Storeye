"""Pydantic schemas for Zone."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ZoneCreate(BaseModel):
    store_id: UUID
    name: str = Field(..., min_length=1, max_length=150)
    description: Optional[str] = Field(default=None, max_length=300)


class ZoneUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    description: Optional[str] = Field(default=None, max_length=300)


class ZoneRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    name: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime


class ZoneList(BaseModel):
    items: list[ZoneRead]
    total: int


class ZoneAnalyticsRead(BaseModel):
    zone_id: UUID
    zone_name: str
    store_id: UUID
    period_start: Optional[datetime]
    period_end: Optional[datetime]
    visits_total: int
    visitors_unique: int
    avg_dwell_seconds: Optional[float]
    max_dwell_seconds: Optional[float]
    p90_dwell_seconds: Optional[float]
    currently_inside: int
    most_recent_visit_at: Optional[datetime]
