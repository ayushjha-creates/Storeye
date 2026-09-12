"""Pydantic schemas for Batch (package-level expiry/metadata)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ..models import BATCH_PRECISION_DAY


class BatchCreate(BaseModel):
    store_id: UUID
    product_id: UUID
    batch_number: Optional[str] = None
    manufacturing_date: Optional[date] = None
    expiry_date: Optional[date] = None
    expiry_date_precision: str = BATCH_PRECISION_DAY
    mrp: Optional[Decimal] = None
    quantity: int = 0


class BatchUpdate(BaseModel):
    manufacturing_date: Optional[date] = None
    expiry_date: Optional[date] = None
    expiry_date_precision: Optional[str] = Field(default=None, max_length=10)
    mrp: Optional[Decimal] = None
    quantity: Optional[int] = None


class BatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    product_id: UUID
    batch_number: Optional[str]
    manufacturing_date: Optional[date]
    expiry_date: Optional[date]
    expiry_date_precision: str
    mrp: Optional[Decimal]
    quantity: int
    created_at: datetime
    updated_at: datetime


class BatchList(BaseModel):
    items: list[BatchRead]
    total: int
