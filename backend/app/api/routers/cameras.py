"""Cameras API routes."""

from __future__ import annotations

from typing import Optional

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..deps import get_db
from ...models import Camera, Store
from ...schemas import CameraCreate, CameraList, CameraRead, CameraUpdate

router = APIRouter(prefix="/cameras", tags=["cameras"])


def _get_camera_or_404(db: Session, camera_id: UUID) -> Camera:
    cam = db.get(Camera, camera_id)
    if cam is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    return cam


@router.get("", response_model=CameraList)
def list_cameras(store_id: Optional[UUID] = None, db: Session = Depends(get_db)):
    stmt = select(Camera)
    if store_id is not None:
        stmt = stmt.where(Camera.store_id == store_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(Camera.name)).all()
    return CameraList(items=[CameraRead.model_validate(i) for i in items], total=total)


@router.post("", response_model=CameraRead, status_code=status.HTTP_201_CREATED)
def create_camera(payload: CameraCreate, db: Session = Depends(get_db)):
    if db.get(Store, payload.store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    cam = Camera(**payload.model_dump())
    db.add(cam)
    db.commit()
    db.refresh(cam)
    return CameraRead.model_validate(cam)


@router.get("/{camera_id}", response_model=CameraRead)
def get_camera(camera_id: UUID, db: Session = Depends(get_db)):
    return CameraRead.model_validate(_get_camera_or_404(db, camera_id))


@router.patch("/{camera_id}", response_model=CameraRead)
def update_camera(camera_id: UUID, payload: CameraUpdate, db: Session = Depends(get_db)):
    cam = _get_camera_or_404(db, camera_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(cam, field, value)
    db.add(cam)
    db.commit()
    db.refresh(cam)
    return CameraRead.model_validate(cam)


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_camera(camera_id: UUID, db: Session = Depends(get_db)):
    cam = _get_camera_or_404(db, camera_id)
    db.delete(cam)
    db.commit()
