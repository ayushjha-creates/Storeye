"""Customers API routes (authenticated, store-scoped).

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
from ...models import Customer, Store, User
from ...schemas import CustomerCreate, CustomerList, CustomerRead, CustomerUpdate

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("", response_model=CustomerList)
def list_customers(
    store_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    sid = effective_store_id(current_user, store_id)
    stmt = select(Customer).where(Customer.store_id == sid)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(Customer.name.nulls_last())).all()
    return CustomerList(
        items=[CustomerRead.model_validate(i) for i in items], total=total
    )


@router.post(
    "", response_model=CustomerRead, status_code=status.HTTP_201_CREATED
)
def create_customer(
    payload: CustomerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    require_same_store(current_user, payload.store_id)
    if db.get(Store, payload.store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    customer = Customer(**payload.model_dump())
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return CustomerRead.model_validate(customer)


@router.get("/{customer_id}", response_model=CustomerRead)
def get_customer(
    customer_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    return CustomerRead.model_validate(scoped_get(db, current_user, Customer, customer_id))


@router.patch("/{customer_id}", response_model=CustomerRead)
def update_customer(
    customer_id: UUID,
    payload: CustomerUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    customer = scoped_get(db, current_user, Customer, customer_id)
    data = payload.model_dump(exclude_unset=True)
    if "store_id" in data and data["store_id"] is not None:
        require_same_store(current_user, data["store_id"])
    for field, value in data.items():
        setattr(customer, field, value)
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return CustomerRead.model_validate(customer)


@router.delete(
    "/{customer_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_customer(
    customer_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    customer = scoped_get(db, current_user, Customer, customer_id)
    db.delete(customer)
    db.commit()