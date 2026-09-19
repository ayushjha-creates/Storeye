"""Pydantic schemas for the Smart Batch Intake API.

Mirrors `app/services/batch_intake`: scanning is read-only (returns an
editable candidate), confirmation is the explicit human-confirmed mutation.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from ..models import BATCH_PRECISION_DAY
from .batch import BatchRead
from .inventory import InventoryMovementRead


class BatchScanCandidateRead(BaseModel):
    """Editable prefill produced by a scan (never auto-committed)."""

    barcode_read: bool = False
    barcode: Optional[str] = None
    product_id: Optional[UUID] = None
    product_name: Optional[str] = None
    product_sku: Optional[str] = None
    product_found: bool = False
    batch_number: Optional[str] = None
    manufacturing_date: Optional[date] = None
    expiry_date: Optional[date] = None
    expiry_date_precision: str = BATCH_PRECISION_DAY
    mrp: Optional[Decimal] = None
    confidence: Optional[float] = None
    labels_found: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class BatchScanRead(BaseModel):
    store_id: Optional[UUID] = None
    acceptable: bool
    reason: str
    candidate: BatchScanCandidateRead


class BatchConfirmIn(BaseModel):
    store_id: UUID
    product_id: UUID
    quantity: int = Field(..., gt=0)
    batch_number: Optional[str] = None
    manufacturing_date: Optional[date] = None
    expiry_date: Optional[date] = None
    expiry_date_precision: str = BATCH_PRECISION_DAY
    mrp: Optional[Decimal] = None
    reference: Optional[str] = None
    barcode: Optional[str] = None


class BatchReceiptRead(BaseModel):
    movement: InventoryMovementRead
    batch: BatchRead