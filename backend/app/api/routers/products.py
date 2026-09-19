"""Products API routes (authenticated, store-scoped).

Reads require any authenticated role; writes require MANAGER+.
"""

from __future__ import annotations

from typing import Optional

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..authz import effective_store_id, require_same_store, scoped_get
from ..deps import get_db, require_role
from ...core.auth import ROLE_MANAGER
from ...models import Product, Store, User
from ...schemas import ProductCreate, ProductList, ProductRead, ProductUpdate

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=ProductList)
def list_products(
    store_id: Optional[UUID] = None,
    category: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    sid = effective_store_id(current_user, store_id)
    stmt = select(Product).where(Product.store_id == sid)
    if category is not None:
        stmt = stmt.where(Product.category == category)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(Product.name)).all()
    return ProductList(items=[ProductRead.model_validate(i) for i in items], total=total)


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_MANAGER)),
):
    require_same_store(current_user, payload.store_id)
    if db.get(Store, payload.store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    product = Product(**payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return ProductRead.model_validate(product)


@router.get("/{product_id}", response_model=ProductRead)
def get_product(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    return ProductRead.model_validate(scoped_get(db, current_user, Product, product_id))


@router.patch("/{product_id}", response_model=ProductRead)
def update_product(
    product_id: UUID,
    payload: ProductUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_MANAGER)),
):
    product = scoped_get(db, current_user, Product, product_id)
    data = payload.model_dump(exclude_unset=True)
    if "store_id" in data and data["store_id"] is not None:
        require_same_store(current_user, data["store_id"])
    for field, value in data.items():
        setattr(product, field, value)
    db.add(product)
    db.commit()
    db.refresh(product)
    return ProductRead.model_validate(product)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_MANAGER)),
):
    product = scoped_get(db, current_user, Product, product_id)
    db.delete(product)
    db.commit()