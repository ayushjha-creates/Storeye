"""Zones API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..deps import get_db
from ...models import Store, Zone
from ...schemas import ZoneAnalyticsRead, ZoneCreate, ZoneList, ZoneRead, ZoneUpdate
from ...services.journeys import JourneyService

router = APIRouter(prefix="/zones", tags=["zones"])


def _get_zone_or_404(db: Session, zone_id: UUID) -> Zone:
    zone = db.get(Zone, zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail="Zone not found")
    return zone


@router.get("", response_model=ZoneList)
def list_zones(store_id: Optional[UUID] = None, db: Session = Depends(get_db)):
    stmt = select(Zone)
    if store_id is not None:
        stmt = stmt.where(Zone.store_id == store_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(Zone.name)).all()
    return ZoneList(items=[ZoneRead.model_validate(i) for i in items], total=total)


@router.post("", response_model=ZoneRead, status_code=status.HTTP_201_CREATED)
def create_zone(payload: ZoneCreate, db: Session = Depends(get_db)):
    if db.get(Store, payload.store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    zone = Zone(**payload.model_dump())
    db.add(zone)
    db.commit()
    db.refresh(zone)
    return ZoneRead.model_validate(zone)


@router.get("/{zone_id}", response_model=ZoneRead)
def get_zone(zone_id: UUID, db: Session = Depends(get_db)):
    return ZoneRead.model_validate(_get_zone_or_404(db, zone_id))


@router.patch("/{zone_id}", response_model=ZoneRead)
def update_zone(zone_id: UUID, payload: ZoneUpdate, db: Session = Depends(get_db)):
    zone = _get_zone_or_404(db, zone_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(zone, field, value)
    db.add(zone)
    db.commit()
    db.refresh(zone)
    return ZoneRead.model_validate(zone)


@router.delete("/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_zone(zone_id: UUID, db: Session = Depends(get_db)):
    zone = _get_zone_or_404(db, zone_id)
    db.delete(zone)
    db.commit()


@router.get("/{zone_id}/analytics", response_model=ZoneAnalyticsRead)
def zone_analytics(
    zone_id: UUID,
    store_id: Optional[UUID] = None,
    start: Optional[datetime] = Query(default=None),
    end: Optional[datetime] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Anonymous zone analytics (visits, dwell, currently inside)."""
    analytics = JourneyService(db).zone_analytics(
        zone_id=zone_id, store_id=store_id, start=start, end=end
    )
    if analytics is None:
        raise HTTPException(status_code=404, detail="Zone not found")
    return ZoneAnalyticsRead(**analytics)
