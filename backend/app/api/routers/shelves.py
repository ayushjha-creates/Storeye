"""Shelves API routes (authenticated, store-scoped).

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
from ...models import Shelf, Store, User, Zone
from ...schemas import ShelfCreate, ShelfList, ShelfRead, ShelfUpdate

router = APIRouter(prefix="/shelves", tags=["shelves"])


def _validate_parents(db: Session, current_user: User, store_id: UUID, zone_id: UUID) -> None:
    require_same_store(current_user, store_id)
    if db.get(Store, store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    zone = scoped_get(db, current_user, Zone, zone_id)
    if zone.store_id != store_id:
        raise HTTPException(status_code=404, detail="Zone not found")


@router.get("", response_model=ShelfList)
def list_shelves(
    store_id: Optional[UUID] = None,
    zone_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    sid = effective_store_id(current_user, store_id)
    stmt = select(Shelf).where(Shelf.store_id == sid)
    if zone_id is not None:
        zone = scoped_get(db, current_user, Zone, zone_id)
        stmt = stmt.where(Shelf.zone_id == zone.id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(Shelf.code)).all()
    return ShelfList(items=[ShelfRead.model_validate(i) for i in items], total=total)


@router.post("", response_model=ShelfRead, status_code=status.HTTP_201_CREATED)
def create_shelf(
    payload: ShelfCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_MANAGER)),
):
    _validate_parents(db, current_user, payload.store_id, payload.zone_id)
    shelf = Shelf(**payload.model_dump())
    db.add(shelf)
    db.commit()
    db.refresh(shelf)
    return ShelfRead.model_validate(shelf)


@router.get("/{shelf_id}", response_model=ShelfRead)
def get_shelf(
    shelf_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    return ShelfRead.model_validate(scoped_get(db, current_user, Shelf, shelf_id))


@router.patch("/{shelf_id}", response_model=ShelfRead)
def update_shelf(
    shelf_id: UUID,
    payload: ShelfUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_MANAGER)),
):
    shelf = scoped_get(db, current_user, Shelf, shelf_id)
    data = payload.model_dump(exclude_unset=True)
    if "store_id" in data and data["store_id"] is not None:
        require_same_store(current_user, data["store_id"])
    if "zone_id" in data and data["zone_id"] is not None:
        zone = scoped_get(db, current_user, Zone, data["zone_id"])
        if zone.store_id != shelf.store_id:
            raise HTTPException(status_code=404, detail="Zone not found")
    for field, value in data.items():
        setattr(shelf, field, value)
    db.add(shelf)
    db.commit()
    db.refresh(shelf)
    return ShelfRead.model_validate(shelf)


@router.delete("/{shelf_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shelf(
    shelf_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_MANAGER)),
):
    shelf = scoped_get(db, current_user, Shelf, shelf_id)
    db.delete(shelf)
    db.commit()