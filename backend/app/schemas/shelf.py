"""Pydantic schemas for Shelf."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ShelfCreate(BaseModel):
    store_id: UUID
    zone_id: UUID
    code: str = Field(..., min_length=1, max_length=30)
    description: Optional[str] = Field(default=None, max_length=300)


class ShelfUpdate(BaseModel):
    zone_id: Optional[UUID] = None
    code: Optional[str] = Field(default=None, min_length=1, max_length=30)
    description: Optional[str] = Field(default=None, max_length=300)


class ShelfRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    zone_id: UUID
    code: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime


class ShelfList(BaseModel):
    items: list[ShelfRead]
    total: int
