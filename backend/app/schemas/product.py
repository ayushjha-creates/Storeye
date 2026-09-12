"""Pydantic schemas for Product."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProductCreate(BaseModel):
    store_id: UUID
    sku: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=200)
    # Machine-readable product identifier (GTIN/EAN/UPC/Code-39 number), if any.
    barcode: Optional[str] = Field(default=None, max_length=64)
    brand: Optional[str] = Field(default=None, max_length=120)
    category: Optional[str] = Field(default=None, max_length=120)
    unit: str = "unit"
    selling_price: Decimal = Decimal("0")
    cost_price: Optional[Decimal] = None
    tax_rate: Decimal = Decimal("0")
    is_active: bool = True
    # Explicit AI class-name mapping (list of strings). Empty/None = unmapped.
    ai_classes: Optional[list[str]] = None


class ProductUpdate(BaseModel):
    sku: Optional[str] = Field(default=None, min_length=1, max_length=100)
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    barcode: Optional[str] = Field(default=None, max_length=64)
    brand: Optional[str] = Field(default=None, max_length=120)
    category: Optional[str] = Field(default=None, max_length=120)
    unit: Optional[str] = None
    selling_price: Optional[Decimal] = None
    cost_price: Optional[Decimal] = None
    tax_rate: Optional[Decimal] = None
    is_active: Optional[bool] = None
    ai_classes: Optional[list[str]] = None


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    sku: str
    name: str
    barcode: Optional[str] = None
    brand: Optional[str]
    category: Optional[str]
    unit: str
    selling_price: Decimal
    cost_price: Optional[Decimal]
    tax_rate: Decimal
    is_active: bool
    ai_classes: Optional[list[str]] = None
    created_at: datetime
    updated_at: datetime


class ProductList(BaseModel):
    items: list[ProductRead]
    total: int
