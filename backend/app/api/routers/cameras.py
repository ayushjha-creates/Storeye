"""Cameras API routes (authenticated, store-scoped).

Reads require any authenticated role; writes require MANAGER+.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..authz import effective_store_id, require_same_store, scoped_get
from ..deps import get_db, require_role
from ...core.auth import ROLE_MANAGER
from ...models import Camera, Store, User
from ...schemas import CameraCreate, CameraList, CameraRead, CameraUpdate

router = APIRouter(prefix="/cameras", tags=["cameras"])


@router.get("", response_model=CameraList)
def list_cameras(
    store_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    sid = effective_store_id(current_user, store_id)
    stmt = select(Camera).where(Camera.store_id == sid)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(Camera.name)).all()
    return CameraList(items=[CameraRead.model_validate(i) for i in items], total=total)


@router.post("", response_model=CameraRead, status_code=status.HTTP_201_CREATED)
def create_camera(
    payload: CameraCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_MANAGER)),
):
    require_same_store(current_user, payload.store_id)
    if db.get(Store, payload.store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    cam = Camera(**payload.model_dump())
    db.add(cam)
    db.commit()
    db.refresh(cam)
    return CameraRead.model_validate(cam)


@router.get("/{camera_id}", response_model=CameraRead)
def get_camera(
    camera_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    return CameraRead.model_validate(scoped_get(db, current_user, Camera, camera_id))


@router.patch("/{camera_id}", response_model=CameraRead)
def update_camera(
    camera_id: UUID,
    payload: CameraUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_MANAGER)),
):
    cam = scoped_get(db, current_user, Camera, camera_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(cam, field, value)
    db.add(cam)
    db.commit()
    db.refresh(cam)
    return CameraRead.model_validate(cam)


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_camera(
    camera_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_MANAGER)),
):
    cam = scoped_get(db, current_user, Camera, camera_id)
    _cleanup_demo_source(cam)
    db.delete(cam)
    db.commit()


def _cleanup_demo_source(cam: Camera) -> None:
    """Remove the uploaded demo clip when its camera is deleted.

    Only files that live under the app-managed demo-video directory are ever
    touched; a user-configured file/USB source is never deleted.
    """
    source = (cam.config or {}).get("source")
    if not source or cam.camera_type != "file":
        return
    try:
        from ...core.config import get_settings

        demo_root = get_settings().DEMO_VIDEO_DIR
        src = Path(str(source))
        # Resolve() guard: only delete files strictly inside the demo dir.
        if src.is_file() and src.resolve().is_relative_to(demo_root.resolve()):
            src.unlink(missing_ok=True)
    except Exception:  # pragma: no cover - defensive; never block deletion
        pass