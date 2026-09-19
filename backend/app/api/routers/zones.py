"""Zones API routes (authenticated, store-scoped).

Reads require any authenticated role; writes require MANAGER+.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..authz import effective_store_id, require_same_store, scoped_get
from ..deps import get_db, require_role
from ...core.auth import ROLE_MANAGER
from ...models import Store, User, Zone
from ...schemas import ZoneAnalyticsRead, ZoneCreate, ZoneList, ZoneRead, ZoneUpdate
from ...services.journeys import JourneyService

router = APIRouter(prefix="/zones", tags=["zones"])


@router.get("", response_model=ZoneList)
def list_zones(
    store_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    sid = effective_store_id(current_user, store_id)
    stmt = select(Zone).where(Zone.store_id == sid)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(Zone.name)).all()
    return ZoneList(items=[ZoneRead.model_validate(i) for i in items], total=total)


@router.post("", response_model=ZoneRead, status_code=status.HTTP_201_CREATED)
def create_zone(
    payload: ZoneCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_MANAGER)),
):
    require_same_store(current_user, payload.store_id)
    if db.get(Store, payload.store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    zone = Zone(**payload.model_dump())
    db.add(zone)
    db.commit()
    db.refresh(zone)
    return ZoneRead.model_validate(zone)


@router.get("/{zone_id}", response_model=ZoneRead)
def get_zone(
    zone_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    return ZoneRead.model_validate(scoped_get(db, current_user, Zone, zone_id))


@router.patch("/{zone_id}", response_model=ZoneRead)
def update_zone(
    zone_id: UUID,
    payload: ZoneUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_MANAGER)),
):
    zone = scoped_get(db, current_user, Zone, zone_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(zone, field, value)
    db.add(zone)
    db.commit()
    db.refresh(zone)
    return ZoneRead.model_validate(zone)


@router.delete("/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_zone(
    zone_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(ROLE_MANAGER)),
):
    zone = scoped_get(db, current_user, Zone, zone_id)
    db.delete(zone)
    db.commit()


@router.get("/{zone_id}/analytics", response_model=ZoneAnalyticsRead)
def zone_analytics(
    zone_id: UUID,
    store_id: Optional[UUID] = None,
    start: Optional[datetime] = Query(default=None),
    end: Optional[datetime] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    """Anonymous zone analytics (visits, dwell, currently inside)."""
    zone = scoped_get(db, current_user, Zone, zone_id)
    analytics = JourneyService(db).zone_analytics(
        zone_id=zone_id,
        store_id=store_id or zone.store_id,
        start=start,
        end=end,
    )
    if analytics is None:
        raise HTTPException(status_code=404, detail="Zone not found")
    return ZoneAnalyticsRead(**analytics)