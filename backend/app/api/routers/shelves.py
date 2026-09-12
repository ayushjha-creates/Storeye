"""Shelves API routes."""

from __future__ import annotations

from typing import Optional

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..deps import get_db
from ...models import Shelf, Store, Zone
from ...schemas import ShelfCreate, ShelfList, ShelfRead, ShelfUpdate

router = APIRouter(prefix="/shelves", tags=["shelves"])


def _get_shelf_or_404(db: Session, shelf_id: UUID) -> Shelf:
    shelf = db.get(Shelf, shelf_id)
    if shelf is None:
        raise HTTPException(status_code=404, detail="Shelf not found")
    return shelf


def _validate_parents(db: Session, store_id: UUID, zone_id: UUID) -> None:
    if db.get(Store, store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    if db.get(Zone, zone_id) is None:
        raise HTTPException(status_code=404, detail="Zone not found")


@router.get("", response_model=ShelfList)
def list_shelves(
    store_id: Optional[UUID] = None,
    zone_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
):
    stmt = select(Shelf)
    if store_id is not None:
        stmt = stmt.where(Shelf.store_id == store_id)
    if zone_id is not None:
        stmt = stmt.where(Shelf.zone_id == zone_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(Shelf.code)).all()
    return ShelfList(items=[ShelfRead.model_validate(i) for i in items], total=total)


@router.post("", response_model=ShelfRead, status_code=status.HTTP_201_CREATED)
def create_shelf(payload: ShelfCreate, db: Session = Depends(get_db)):
    _validate_parents(db, payload.store_id, payload.zone_id)
    shelf = Shelf(**payload.model_dump())
    db.add(shelf)
    db.commit()
    db.refresh(shelf)
    return ShelfRead.model_validate(shelf)


@router.get("/{shelf_id}", response_model=ShelfRead)
def get_shelf(shelf_id: UUID, db: Session = Depends(get_db)):
    return ShelfRead.model_validate(_get_shelf_or_404(db, shelf_id))


@router.patch("/{shelf_id}", response_model=ShelfRead)
def update_shelf(shelf_id: UUID, payload: ShelfUpdate, db: Session = Depends(get_db)):
    shelf = _get_shelf_or_404(db, shelf_id)
    data = payload.model_dump(exclude_unset=True)
    if "zone_id" in data and data["zone_id"] is not None:
        if db.get(Zone, data["zone_id"]) is None:
            raise HTTPException(status_code=404, detail="Zone not found")
    for field, value in data.items():
        setattr(shelf, field, value)
    db.add(shelf)
    db.commit()
    db.refresh(shelf)
    return ShelfRead.model_validate(shelf)


@router.delete("/{shelf_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shelf(shelf_id: UUID, db: Session = Depends(get_db)):
    shelf = _get_shelf_or_404(db, shelf_id)
    db.delete(shelf)
    db.commit()