"""Pydantic schemas for Customer."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CustomerCreate(BaseModel):
    store_id: UUID
    mobile: str = Field(..., min_length=1, max_length=30)
    name: Optional[str] = Field(default=None, max_length=150)


class CustomerUpdate(BaseModel):
    mobile: Optional[str] = Field(default=None, min_length=1, max_length=30)
    name: Optional[str] = Field(default=None, max_length=150)


class CustomerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    mobile: str
    name: Optional[str]
    created_at: datetime
    updated_at: datetime


class CustomerList(BaseModel):
    items: list[CustomerRead]
    total: int
