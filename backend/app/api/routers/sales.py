"""Sales API routes.

BILLING/SALE RULE
-----------------
Sales are MANUAL records of completed transactions (the shopkeeper creates
them). There is NO camera/AI sale inference. A sale records items/prices;
it does NOT automatically mutate inventory — stock changes remain explicit
operations through the inventory service.
"""

from __future__ import annotations

from typing import Optional

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..deps import get_db
from ...models import Product, Sale, SaleItem, Store
from ...schemas import SaleCreate, SaleList, SaleRead

router = APIRouter(prefix="/sales", tags=["sales"])


def _get_sale_or_404(db: Session, sale_id: UUID) -> Sale:
    sale = db.get(Sale, sale_id)
    if sale is None:
        raise HTTPException(status_code=404, detail="Sale not found")
    return sale


def _validate_items(db: Session, payload: SaleCreate) -> None:
    if db.get(Store, payload.store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    for item in payload.items:
        if db.get(Product, item.product_id) is None:
            raise HTTPException(
                status_code=404,
                detail=f"Product {item.product_id} not found",
            )


@router.get("", response_model=SaleList)
def list_sales(
    store_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
):
    stmt = select(Sale)
    if store_id is not None:
        stmt = stmt.where(Sale.store_id == store_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(Sale.sale_timestamp_utc.desc())).all()
    return SaleList(
        items=[SaleRead.model_validate(i) for i in items], total=total
    )


@router.post(
    "", response_model=SaleRead, status_code=status.HTTP_201_CREATED
)
def create_sale(payload: SaleCreate, db: Session = Depends(get_db)):
    _validate_items(db, payload)
    sale = Sale(
        store_id=payload.store_id,
        subtotal=payload.subtotal,
        tax_total=payload.tax_total,
        total=payload.total,
        payment_method=payload.payment_method,
        customer_id=payload.customer_id,
    )
    sale.items = [
        SaleItem(
            product_id=i.product_id,
            quantity=i.quantity,
            unit_price=i.unit_price,
            tax=i.tax,
            line_total=i.line_total,
        )
        for i in payload.items
    ]
    db.add(sale)
    db.commit()
    db.refresh(sale)
    return SaleRead.model_validate(sale)


@router.get("/{sale_id}", response_model=SaleRead)
def get_sale(sale_id: UUID, db: Session = Depends(get_db)):
    return SaleRead.model_validate(_get_sale_or_404(db, sale_id))


@router.delete("/{sale_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sale(sale_id: UUID, db: Session = Depends(get_db)):
    sale = _get_sale_or_404(db, sale_id)
    db.delete(sale)
    db.commit()
