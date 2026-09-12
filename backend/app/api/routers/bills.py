"""Bills API routes.

BILLING RULE
------------
Billing is MANUAL. The shopkeeper creates the bill by selecting
products/quantities. There is NO AI-generated or predicted billing, and no
purchase inference from camera. Digital delivery (WhatsApp/SMS) is a later
milestone — here we only persist and expose the bill.
"""

from __future__ import annotations

from typing import Optional

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..deps import get_db
from ...models import Bill, BillItem, Customer, Product, Sale, Store
from ...schemas import BillCreate, BillList, BillRead, BillUpdate

router = APIRouter(prefix="/bills", tags=["bills"])


def _get_bill_or_404(db: Session, bill_id: UUID) -> Bill:
    bill = db.get(Bill, bill_id)
    if bill is None:
        raise HTTPException(status_code=404, detail="Bill not found")
    return bill


def _validate_refs(db: Session, payload: BillCreate) -> None:
    if db.get(Store, payload.store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    if payload.sale_id is not None and db.get(Sale, payload.sale_id) is None:
        raise HTTPException(status_code=404, detail="Sale not found")
    if payload.customer_id is not None and db.get(Customer, payload.customer_id) is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    for item in payload.items:
        if db.get(Product, item.product_id) is None:
            raise HTTPException(
                status_code=404,
                detail=f"Product {item.product_id} not found",
            )


@router.get("", response_model=BillList)
def list_bills(
    store_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
):
    stmt = select(Bill)
    if store_id is not None:
        stmt = stmt.where(Bill.store_id == store_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(Bill.created_at.desc())).all()
    return BillList(
        items=[BillRead.model_validate(i) for i in items], total=total
    )


@router.post(
    "", response_model=BillRead, status_code=status.HTTP_201_CREATED
)
def create_bill(payload: BillCreate, db: Session = Depends(get_db)):
    _validate_refs(db, payload)
    bill = Bill(
        store_id=payload.store_id,
        bill_number=payload.bill_number,
        sale_id=payload.sale_id,
        customer_id=payload.customer_id,
        subtotal=payload.subtotal,
        tax_total=payload.tax_total,
        total=payload.total,
        delivery_status=payload.delivery_status,
    )
    bill.items = [
        BillItem(
            product_id=i.product_id,
            quantity=i.quantity,
            unit_price=i.unit_price,
            tax=i.tax,
            line_total=i.line_total,
        )
        for i in payload.items
    ]
    db.add(bill)
    db.commit()
    db.refresh(bill)
    return BillRead.model_validate(bill)


@router.get("/{bill_id}", response_model=BillRead)
def get_bill(bill_id: UUID, db: Session = Depends(get_db)):
    return BillRead.model_validate(_get_bill_or_404(db, bill_id))


@router.patch("/{bill_id}", response_model=BillRead)
def update_bill(
    bill_id: UUID,
    payload: BillUpdate,
    db: Session = Depends(get_db),
):
    bill = _get_bill_or_404(db, bill_id)
    if payload.customer_id is not None:
        if db.get(Customer, payload.customer_id) is None:
            raise HTTPException(status_code=404, detail="Customer not found")
        bill.customer_id = payload.customer_id
    if payload.delivery_status is not None:
        bill.delivery_status = payload.delivery_status
    db.add(bill)
    db.commit()
    db.refresh(bill)
    return BillRead.model_validate(bill)


@router.delete("/{bill_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bill(bill_id: UUID, db: Session = Depends(get_db)):
    bill = _get_bill_or_404(db, bill_id)
    db.delete(bill)
    db.commit()
