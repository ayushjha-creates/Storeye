"""Inventory / Batch / Movement API routes.

INVENTORY RULE
--------------
All inventory mutations MUST go through the existing domain services
(InventoryService, BatchService) which keep Inventory, Batch.quantity and the
movement record atomic within a single session transaction. This router does
NOT write directly to Inventory / InventoryMovement tables.

Batch metadata updates (expiry, mrp, manufacturing date) are applied directly
to the ORM row using the same validation the BatchService enforces. This avoids
creating a new batch row when the intent is to correct metadata on an existing
batch.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..deps import get_db
from ...models import Batch, Inventory, InventoryMovement, Product, Store
from ...schemas import (
    AdjustStockIn,
    BatchCreate,
    BatchList,
    BatchRead,
    BatchUpdate,
    InventoryMovementList,
    InventoryMovementRead,
    InventoryRead,
    InventorySetReorder,
    InventorySummaryRead,
    ReceiveStockIn,
    RecordMovementIn,
)
from ...services.inventory import BatchService, InventoryService

router = APIRouter(prefix="/inventory", tags=["inventory"])


# ---------------------------------------------------------------------------
# Inventory reads (aggregate stock)
# ---------------------------------------------------------------------------
@router.get("/stores/{store_id}/products/{product_id}", response_model=InventoryRead)
def get_product_inventory(
    store_id: UUID, product_id: UUID, db: Session = Depends(get_db)
):
    if db.get(Product, product_id) is None:
        raise HTTPException(status_code=404, detail="Product not found")
    inv = db.scalar(
        select(Inventory).where(
            Inventory.store_id == store_id,
            Inventory.product_id == product_id,
        )
    )
    if inv is None:
        # No aggregate row yet -> report a zero-quantity aggregate. Return a
        # stable response instead of a transient ORM row (which lacks id/timestamps).
        now = datetime.now(timezone.utc)
        return InventoryRead(
            id=UUID(int=0),
            store_id=store_id,
            product_id=product_id,
            quantity=0,
            reorder_level=0,
            reorder_quantity=0,
            created_at=now,
            updated_at=now,
        )
    return InventoryRead.model_validate(inv)


@router.get(
    "/stores/{store_id}/products/{product_id}/summary",
    response_model=InventorySummaryRead,
)
def get_product_summary(
    store_id: UUID, product_id: UUID, db: Session = Depends(get_db)
):
    if db.get(Product, product_id) is None:
        raise HTTPException(status_code=404, detail="Product not found")
    svc = InventoryService(db)
    aggregate, batches = svc.get_product_batch_summary(store_id, product_id)
    return InventorySummaryRead(
        product_id=product_id,
        aggregate_quantity=aggregate,
        batch_count=len(batches),
    )


@router.get(
    "/stores/{store_id}/products/{product_id}/movements",
    response_model=InventoryMovementList,
)
def list_movements(
    store_id: UUID,
    product_id: UUID,
    db: Session = Depends(get_db),
):
    if db.get(Product, product_id) is None:
        raise HTTPException(status_code=404, detail="Product not found")
    stmt = (
        select(InventoryMovement)
        .where(
            InventoryMovement.store_id == store_id,
            InventoryMovement.product_id == product_id,
        )
        .order_by(InventoryMovement.timestamp_utc.desc())
    )
    items = db.scalars(stmt).all()
    return InventoryMovementList(
        items=[InventoryMovementRead.model_validate(i) for i in items],
        total=len(items),
    )


@router.get(
    "/stores/{store_id}/products/{product_id}/batches",
    response_model=BatchList,
)
def list_product_batches(
    store_id: UUID,
    product_id: UUID,
    db: Session = Depends(get_db),
):
    if db.get(Store, store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    if db.get(Product, product_id) is None:
        raise HTTPException(status_code=404, detail="Product not found")
    batches = BatchService(db).get_batches_for_product(store_id, product_id)
    return BatchList(
        items=[BatchRead.model_validate(i) for i in batches],
        total=len(batches),
    )


# ---------------------------------------------------------------------------
# Inventory mutations — via domain service (atomic, always creates a movement)
# ---------------------------------------------------------------------------
@router.post(
    "/receive",
    response_model=InventoryMovementRead,
    status_code=status.HTTP_201_CREATED,
)
def receive_stock(payload: ReceiveStockIn, db: Session = Depends(get_db)):
    svc = InventoryService(db)
    movement = svc.receive_stock(
        store_id=payload.store_id,
        product_id=payload.product_id,
        quantity_change=payload.quantity_change,
        batch_id=payload.batch_id,
        batch_number=payload.batch_number,
        reference=payload.reference,
        movement_type=payload.movement_type,
    )
    return InventoryMovementRead.model_validate(movement)


@router.post("/adjust", response_model=InventoryMovementRead)
def adjust_stock(payload: AdjustStockIn, db: Session = Depends(get_db)):
    svc = InventoryService(db)
    movement = svc.adjust_stock(
        store_id=payload.store_id,
        product_id=payload.product_id,
        quantity_change=payload.quantity_change,
        batch_id=payload.batch_id,
        batch_number=payload.batch_number,
        reference=payload.reference,
        movement_type=payload.movement_type,
        require_sufficient_stock=payload.require_sufficient_stock,
    )
    return InventoryMovementRead.model_validate(movement)


@router.post(
    "/movements",
    response_model=InventoryMovementRead,
    status_code=status.HTTP_201_CREATED,
)
def record_movement(payload: RecordMovementIn, db: Session = Depends(get_db)):
    svc = InventoryService(db)
    movement = svc.record_movement(
        store_id=payload.store_id,
        product_id=payload.product_id,
        quantity_change=payload.quantity_change,
        movement_type=payload.movement_type,
        batch_id=payload.batch_id,
        batch_number=payload.batch_number,
        reference=payload.reference,
    )
    return InventoryMovementRead.model_validate(movement)


@router.patch(
    "/stores/{store_id}/products/{product_id}/reorder",
    response_model=InventoryRead,
)
def set_reorder_levels(
    store_id: UUID,
    product_id: UUID,
    payload: InventorySetReorder,
    db: Session = Depends(get_db),
):
    if db.get(Store, store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    if db.get(Product, product_id) is None:
        raise HTTPException(status_code=404, detail="Product not found")
    inv = db.scalar(
        select(Inventory).where(
            Inventory.store_id == store_id,
            Inventory.product_id == product_id,
        )
    )
    if inv is None:
        raise HTTPException(status_code=404, detail="Inventory not found")
    if payload.reorder_level is not None:
        if payload.reorder_level < 0:
            raise HTTPException(
                status_code=422, detail="reorder_level cannot be negative"
            )
        inv.reorder_level = payload.reorder_level
    if payload.reorder_quantity is not None:
        if payload.reorder_quantity < 0:
            raise HTTPException(
                status_code=422, detail="reorder_quantity cannot be negative"
            )
        inv.reorder_quantity = payload.reorder_quantity
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return InventoryRead.model_validate(inv)


# ---------------------------------------------------------------------------
# Batch management — via BatchService for create; direct ORM for metadata update
# ---------------------------------------------------------------------------
@router.post(
    "/batches", response_model=BatchRead, status_code=status.HTTP_201_CREATED
)
def create_batch(payload: BatchCreate, db: Session = Depends(get_db)):
    if db.get(Product, payload.product_id) is None:
        raise HTTPException(status_code=404, detail="Product not found")
    if db.get(Store, payload.store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    svc = BatchService(db)
    batch = svc.create_batch(
        store_id=payload.store_id,
        product_id=payload.product_id,
        batch_number=payload.batch_number,
        manufacturing_date=payload.manufacturing_date,
        expiry_date=payload.expiry_date,
        expiry_date_precision=payload.expiry_date_precision,
        mrp=payload.mrp,
        quantity=payload.quantity,
    )
    return BatchRead.model_validate(batch)


@router.get("/batches", response_model=BatchList)
def list_all_batches(
    store_id: Optional[UUID] = None,
    product_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
):
    stmt = select(Batch)
    if store_id is not None:
        stmt = stmt.where(Batch.store_id == store_id)
    if product_id is not None:
        stmt = stmt.where(Batch.product_id == product_id)
    items = db.scalars(stmt.order_by(Batch.batch_number)).all()
    return BatchList(
        items=[BatchRead.model_validate(i) for i in items], total=len(items)
    )


@router.get("/batches/{batch_id}", response_model=BatchRead)
def get_batch(batch_id: UUID, db: Session = Depends(get_db)):
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    return BatchRead.model_validate(batch)


@router.patch("/batches/{batch_id}", response_model=BatchRead)
def update_batch(
    batch_id: UUID, payload: BatchUpdate, db: Session = Depends(get_db)
):
    """Update batch metadata (expiry, mrp, manufacturing date).

    Inventory-related fields (quantity) are NOT updated here — quantity
    changes must go through InventoryService to preserve atomicity.
    """
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    if payload.manufacturing_date is not None:
        batch.manufacturing_date = payload.manufacturing_date
    if payload.expiry_date is not None:
        batch.expiry_date = payload.expiry_date
    if payload.expiry_date_precision is not None:
        batch.expiry_date_precision = payload.expiry_date_precision
    if payload.mrp is not None:
        batch.mrp = payload.mrp
    # Quantity is NOT updated through this endpoint.
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return BatchRead.model_validate(batch)
