"""Stores API routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..deps import get_db
from ...models import Store
from ...schemas import StoreCreate, StoreList, StoreRead, StoreUpdate

router = APIRouter(prefix="/stores", tags=["stores"])


@router.get("", response_model=StoreList)
def list_stores(db: Session = Depends(get_db)):
    total = db.scalar(select(func.count(Store.id))) or 0
    items = db.scalars(select(Store).order_by(Store.name)).all()
    return StoreList(items=[StoreRead.model_validate(i) for i in items], total=total)


@router.post("", response_model=StoreRead, status_code=status.HTTP_201_CREATED)
def create_store(payload: StoreCreate, db: Session = Depends(get_db)):
    store = Store(**payload.model_dump())
    db.add(store)
    db.commit()
    db.refresh(store)
    return StoreRead.model_validate(store)


@router.get("/{store_id}", response_model=StoreRead)
def get_store(store_id: UUID, db: Session = Depends(get_db)):
    store = db.get(Store, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")
    return StoreRead.model_validate(store)


@router.patch("/{store_id}", response_model=StoreRead)
def update_store(store_id: UUID, payload: StoreUpdate, db: Session = Depends(get_db)):
    store = db.get(Store, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(store, field, value)
    db.add(store)
    db.commit()
    db.refresh(store)
    return StoreRead.model_validate(store)


@router.delete("/{store_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_store(store_id: UUID, db: Session = Depends(get_db)):
    store = db.get(Store, store_id)
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")
    db.delete(store)
    db.commit()
