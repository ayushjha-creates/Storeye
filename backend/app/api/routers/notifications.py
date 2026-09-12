"""Notifications API routes."""

from __future__ import annotations

from typing import Optional

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..deps import get_db
from ...models import Notification, Store
from ...schemas import (
    NotificationCreate,
    NotificationList,
    NotificationRead,
    NotificationUpdate,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _get_notification_or_404(db: Session, notif_id: UUID) -> Notification:
    notif = db.get(Notification, notif_id)
    if notif is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return notif


@router.get("", response_model=NotificationList)
def list_notifications(
    store_id: Optional[UUID] = None,
    is_read: Optional[bool] = None,
    notif_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    stmt = select(Notification)
    if store_id is not None:
        stmt = stmt.where(Notification.store_id == store_id)
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
    payload: NotificationCreate, db: Session = Depends(get_db)
):
    if db.get(Store, payload.store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    notif = Notification(**payload.model_dump())
    db.add(notif)
    db.commit()
    db.refresh(notif)
    return NotificationRead.model_validate(notif)


@router.get("/{notif_id}", response_model=NotificationRead)
def get_notification(notif_id: UUID, db: Session = Depends(get_db)):
    return NotificationRead.model_validate(
        _get_notification_or_404(db, notif_id)
    )


@router.patch("/{notif_id}", response_model=NotificationRead)
def update_notification(
    notif_id: UUID,
    payload: NotificationUpdate,
    db: Session = Depends(get_db),
):
    notif = _get_notification_or_404(db, notif_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(notif, field, value)
    db.add(notif)
    db.commit()
    db.refresh(notif)
    return NotificationRead.model_validate(notif)


@router.delete("/{notif_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notification(notif_id: UUID, db: Session = Depends(get_db)):
    notif = _get_notification_or_404(db, notif_id)
    db.delete(notif)
    db.commit()
