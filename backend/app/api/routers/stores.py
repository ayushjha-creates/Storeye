"""Stores API routes (authenticated, OWNER-managed).

Store lifecycle is OWNER-only. A user may read and modify only their own
store; cross-store identifiers are indistinguishable from missing ones (404).
Creating a store provisions a new tenant and does not move the acting user.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..authz import scoped_get
from ..deps import get_db, require_role
from ...core.auth import ROLE_OWNER
from ...models import Store, User
from ...schemas import StoreCreate, StoreList, StoreRead, StoreUpdate

router = APIRouter(prefix="/stores", tags=["stores"])


@router.get("", response_model=StoreList)
def list_stores(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    if current_user.store_id is None:
        return StoreList(items=[], total=0)
    items = db.scalars(
        select(Store).where(Store.id == current_user.store_id)
    ).all()
    return StoreList(items=[StoreRead.model_validate(i) for i in items], total=len(items))


@router.post("", response_model=StoreRead, status_code=status.HTTP_201_CREATED)
def create_store(
    payload: StoreCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_OWNER)),
):
    store = Store(**payload.model_dump())
    db.add(store)
    db.commit()
    db.refresh(store)
    return StoreRead.model_validate(store)


@router.get("/{store_id}", response_model=StoreRead)
def get_store(
    store_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    return StoreRead.model_validate(scoped_get(db, current_user, Store, store_id))


@router.patch("/{store_id}", response_model=StoreRead)
def update_store(
    store_id: UUID,
    payload: StoreUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_OWNER)),
):
    store = scoped_get(db, current_user, Store, store_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(store, field, value)
    db.add(store)
    db.commit()
    db.refresh(store)
    return StoreRead.model_validate(store)


@router.delete("/{store_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_store(
    store_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_OWNER)),
):
    store = scoped_get(db, current_user, Store, store_id)
    db.delete(store)
    db.commit()