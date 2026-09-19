"""Notifications API routes (authenticated, store-scoped).

Reads require any authenticated role (STAFF+); writes require MANAGER+.
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
from ...models import Notification, Store, User
from ...schemas import (
    NotificationCreate,
    NotificationList,
    NotificationRead,
    NotificationUpdate,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationList)
def list_notifications(
    store_id: Optional[UUID] = None,
    is_read: Optional[bool] = None,
    notif_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    sid = effective_store_id(current_user, store_id)
    stmt = select(Notification).where(Notification.store_id == sid)
    if is_read is not None:
        stmt = stmt.where(Notification.is_read.is_(is_read))
    if notif_type is not None:
        stmt = stmt.where(Notification.notif_type == notif_type)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(Notification.created_at.desc())).all()
    return NotificationList(
        items=[NotificationRead.model_validate(i) for i in items], total=total
    )


@router.post(
    "", response_model=NotificationRead, status_code=status.HTTP_201_CREATED
)
def create_notification(
    payload: NotificationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_MANAGER)),
):
    require_same_store(current_user, payload.store_id)
    if db.get(Store, payload.store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    notif = Notification(**payload.model_dump())
    db.add(notif)
    db.commit()
    db.refresh(notif)
    return NotificationRead.model_validate(notif)


@router.get("/{notif_id}", response_model=NotificationRead)
def get_notification(
    notif_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    return NotificationRead.model_validate(
        scoped_get(db, current_user, Notification, notif_id)
    )


@router.patch("/{notif_id}", response_model=NotificationRead)
def update_notification(
    notif_id: UUID,
    payload: NotificationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_MANAGER)),
):
    notif = scoped_get(db, current_user, Notification, notif_id)
    data = payload.model_dump(exclude_unset=True)
    if "store_id" in data and data["store_id"] is not None:
        require_same_store(current_user, data["store_id"])
    for field, value in data.items():
        setattr(notif, field, value)
    db.add(notif)
    db.commit()
    db.refresh(notif)
    return NotificationRead.model_validate(notif)


@router.delete("/{notif_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notification(
    notif_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_MANAGER)),
):
    notif = scoped_get(db, current_user, Notification, notif_id)
    db.delete(notif)
    db.commit()