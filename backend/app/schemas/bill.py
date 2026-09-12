"""Pydantic schemas for Bill and BillItem.

Billing is MANUAL. A Bill is created explicitly by the shopkeeper; there is
no camera/AI billing. Digital delivery (WhatsApp/SMS) is a later milestone.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BillItemCreate(BaseModel):
    product_id: UUID
    quantity: int = Field(..., gt=0)
    unit_price: Decimal
    tax: Decimal = Decimal("0")
    line_total: Decimal


class BillCreate(BaseModel):
    store_id: UUID
    bill_number: str = Field(..., min_length=1, max_length=50)
    sale_id: Optional[UUID] = None
    customer_id: Optional[UUID] = None
    subtotal: Decimal = Decimal("0")
    tax_total: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    delivery_status: str = "DRAFT"
    items: list[BillItemCreate] = []


class BillUpdate(BaseModel):
    delivery_status: Optional[str] = Field(default=None, max_length=30)
    customer_id: Optional[UUID] = None


class BillItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    bill_id: UUID
    product_id: UUID
    quantity: int
    unit_price: Decimal
    tax: Decimal
    line_total: Decimal


class BillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    bill_number: str
    sale_id: Optional[UUID]
    customer_id: Optional[UUID]
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    delivery_status: str
    items: list[BillItemRead]
    created_at: datetime
    updated_at: datetime


class BillList(BaseModel):
    items: list[BillRead]
    total: int
