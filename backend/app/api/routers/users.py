"""Users API routes."""

from __future__ import annotations

from typing import Optional

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..deps import get_db
from ...models import Store, User
from ...schemas import UserCreate, UserList, UserRead, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


def _get_user_or_404(db: Session, user_id: UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def _require_store(db: Session, store_id: UUID) -> None:
    if db.get(Store, store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")


@router.get("", response_model=UserList)
def list_users(store_id: Optional[UUID] = None, db: Session = Depends(get_db)):
    stmt = select(User)
    if store_id is not None:
        stmt = stmt.where(User.store_id == store_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(User.name)).all()
    return UserList(items=[UserRead.model_validate(i) for i in items], total=total)


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    _require_store(db, payload.store_id)
    user = User(**payload.model_dump())
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserRead.model_validate(user)


@router.get("/{user_id}", response_model=UserRead)
def get_user(user_id: UUID, db: Session = Depends(get_db)):
    return UserRead.model_validate(_get_user_or_404(db, user_id))


@router.patch("/{user_id}", response_model=UserRead)
def update_user(user_id: UUID, payload: UserUpdate, db: Session = Depends(get_db)):
    user = _get_user_or_404(db, user_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserRead.model_validate(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: UUID, db: Session = Depends(get_db)):
    user = _get_user_or_404(db, user_id)
    db.delete(user)
    db.commit()
