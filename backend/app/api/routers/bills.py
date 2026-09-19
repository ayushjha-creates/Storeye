"""Bills API routes (authenticated, store-scoped).

BILLING RULE
------------
Billing is MANUAL. The shopkeeper creates the bill by selecting
products/quantities. There is NO AI-generated or predicted billing, and no
purchase inference from camera. When SMS receipts are enabled (M31) and the
bill has a customer with a phone number, a receipt SMS is queued AFTER the
bill commit — best-effort, never blocking billing.

Reads and writes require any authenticated role (STAFF+).
"""

from __future__ import annotations

from typing import Optional

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..authz import effective_store_id, require_same_store, scoped_get
from ..deps import get_db, require_role
from ...models import Bill, BillItem, Customer, Product, Sale, Store, User
from ...schemas import BillCreate, BillList, BillRead, BillUpdate

router = APIRouter(prefix="/bills", tags=["bills"])


def _validate_refs(db: Session, current_user: User, payload: BillCreate) -> None:
    require_same_store(current_user, payload.store_id)
    if db.get(Store, payload.store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    if payload.sale_id is not None and scoped_get(db, current_user, Sale, payload.sale_id).store_id != payload.store_id:
        raise HTTPException(status_code=404, detail="Sale not found")
    if payload.customer_id is not None and scoped_get(db, current_user, Customer, payload.customer_id).store_id != payload.store_id:
        raise HTTPException(status_code=404, detail="Customer not found")
    for item in payload.items:
        if scoped_get(db, current_user, Product, item.product_id).store_id != payload.store_id:
            raise HTTPException(
                status_code=404,
                detail=f"Product {item.product_id} not found",
            )


@router.get("", response_model=BillList)
def list_bills(
    store_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    sid = effective_store_id(current_user, store_id)
    stmt = select(Bill).where(Bill.store_id == sid)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(Bill.created_at.desc())).all()
    return BillList(
        items=[BillRead.model_validate(i) for i in items], total=total
    )


@router.post(
    "", response_model=BillRead, status_code=status.HTTP_201_CREATED
)
def create_bill(
    payload: BillCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    _validate_refs(db, current_user, payload)
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
    _maybe_queue_receipt(db, bill)
    return BillRead.model_validate(bill)


def _maybe_queue_receipt(db: Session, bill: Bill) -> None:
    """M31 — auto-queue a receipt SMS for the bill's customer phone number.

    Best-effort and run AFTER the bill commit, so an SMS queue/gateway problem
    can NEVER roll back or block billing. Bills without a customer phone are
    skipped; deployments with SMS disabled are skipped; a missing/cross-store
    customer is skipped defensively (never raises into the response).
    """
    from ...core.config import get_settings

    if not get_settings().SMS_ENABLED or bill.customer_id is None:
        return
    customer = db.get(Customer, bill.customer_id)
    if customer is None or customer.store_id != bill.store_id:
        return
    from ...services.sms.manager import get_sms_worker

    # Only queue when the process-wide SMS worker is actually enabled+runnable;
    # otherwise the row would sit QUEUED forever with no drainer.
    if get_sms_worker() is None:
        return
    store = db.get(Store, bill.store_id)
    from ...services.sms.outbox import SmsOutboxService

    SmsOutboxService(db).enqueue_for_bill(bill, store, customer)


@router.get("/{bill_id}", response_model=BillRead)
def get_bill(
    bill_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    return BillRead.model_validate(scoped_get(db, current_user, Bill, bill_id))


@router.patch("/{bill_id}", response_model=BillRead)
def update_bill(
    bill_id: UUID,
    payload: BillUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    bill = scoped_get(db, current_user, Bill, bill_id)
    if payload.customer_id is not None:
        customer = scoped_get(db, current_user, Customer, payload.customer_id)
        if customer.store_id != bill.store_id:
            raise HTTPException(status_code=404, detail="Customer not found")
        bill.customer_id = payload.customer_id
    if payload.delivery_status is not None:
        bill.delivery_status = payload.delivery_status
    db.add(bill)
    db.commit()
    db.refresh(bill)
    return BillRead.model_validate(bill)


@router.delete("/{bill_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bill(
    bill_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    bill = scoped_get(db, current_user, Bill, bill_id)
    db.delete(bill)
    db.commit()