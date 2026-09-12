"""Pydantic schemas for Store."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StoreCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    address: Optional[str] = Field(default=None, max_length=300)
    city: Optional[str] = Field(default=None, max_length=100)
    phone: Optional[str] = Field(default=None, max_length=30)
    timezone: str = "Asia/Kolkata"


class StoreUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    address: Optional[str] = Field(default=None, max_length=300)
    city: Optional[str] = Field(default=None, max_length=100)
    phone: Optional[str] = Field(default=None, max_length=30)
    timezone: Optional[str] = Field(default=None, max_length=64)


class StoreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    address: Optional[str]
    city: Optional[str]
    phone: Optional[str]
    timezone: str
    created_at: datetime
    updated_at: datetime


class StoreList(BaseModel):
    items: list[StoreRead]
    total: int
