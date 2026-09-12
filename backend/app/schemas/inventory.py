"""Pydantic schemas for Inventory (aggregate stock) and movements."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class InventoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    product_id: UUID
    quantity: int
    reorder_level: int
    reorder_quantity: int
    created_at: datetime
    updated_at: datetime


class InventorySetReorder(BaseModel):
    reorder_level: Optional[int] = None
    reorder_quantity: Optional[int] = None


class ReceiveStockIn(BaseModel):
    store_id: UUID
    product_id: UUID
    quantity_change: int
    batch_id: Optional[UUID] = None
    batch_number: Optional[str] = None
    reference: Optional[str] = None
    movement_type: str = "PURCHASE"


class AdjustStockIn(BaseModel):
    store_id: UUID
    product_id: UUID
    quantity_change: int
    batch_id: Optional[UUID] = None
    batch_number: Optional[str] = None
    reference: Optional[str] = None
    movement_type: str = "ADJUSTMENT"
    require_sufficient_stock: bool = False


class RecordMovementIn(BaseModel):
    store_id: UUID
    product_id: UUID
    quantity_change: int
    movement_type: str
    batch_id: Optional[UUID] = None
    batch_number: Optional[str] = None
    reference: Optional[str] = None


class InventoryMovementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    store_id: UUID
    product_id: UUID
    batch_id: Optional[UUID]
    quantity_change: int
    movement_type: str
    reference: Optional[str]
    timestamp_utc: datetime
    created_at: datetime
    updated_at: datetime


class InventoryMovementList(BaseModel):
    items: list[InventoryMovementRead]
    total: int


class InventorySummaryRead(BaseModel):
    product_id: UUID
    aggregate_quantity: int
    batch_count: int
