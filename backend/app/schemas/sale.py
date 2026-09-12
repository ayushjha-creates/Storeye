"""Pydantic schemas for Sale and SaleItem."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SaleItemCreate(BaseModel):
    product_id: UUID
    quantity: int = Field(..., gt=0)
    unit_price: Decimal
    tax: Decimal = Decimal("0")
    line_total: Decimal


class SaleCreate(BaseModel):
    store_id: UUID
    subtotal: Decimal = Decimal("0")
    tax_total: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    payment_method: Optional[str] = None
    customer_id: Optional[UUID] = None
    items: list[SaleItemCreate] = []


class SaleItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sale_id: UUID
    product_id: UUID
    quantity: int
    unit_price: Decimal
    tax: Decimal
    line_total: Decimal


class SaleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    sale_timestamp_utc: datetime
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    payment_method: Optional[str]
    customer_id: Optional[UUID]
    items: list[SaleItemRead]
    created_at: datetime
    updated_at: datetime


class SaleList(BaseModel):
    items: list[SaleRead]
    total: int
