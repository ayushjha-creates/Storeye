"""Anonymous Customer Journeys API routes (M19).

Endpoints:
    GET /api/journeys                  — paged journey list for a store
    GET /api/journeys/summary          — header KPIs
    GET /api/journeys/{global_person_id} — one journey timeline/detail

Every response is keyed by an OPAQUE `global_person_id`. No faces, no crops,
no embeddings, no biometrics are ever returned.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..deps import get_db
from ...schemas import (
    CameraVisitedRead,
    JourneyDetailRead,
    JourneyItemRead,
    JourneyListRead,
    JourneySummaryRead,
    MostVisitedZoneRead,
    TimelineEventRead,
    TrackAssociationRead,
    TransitionRead,
    ZoneVisitedRead,
    ZoneVisitRead,
)
from ...services.journeys import JourneyService

router = APIRouter(prefix="/journeys", tags=["journeys"])


def _svc(db: Session) -> JourneyService:
    return JourneyService(db)


@router.get("/summary", response_model=JourneySummaryRead)
def journeys_summary(
    store_id: UUID,
    start: Optional[datetime] = Query(default=None, description="Inclusive window start (UTC)"),
    end: Optional[datetime] = Query(default=None, description="Inclusive window end (UTC)"),
    db: Session = Depends(get_db),
):
    """Header KPIs for the Anonymous Customer Journey dashboard."""
    s = _svc(db).journey_summary(store_id=store_id, start=start, end=end)
    most = s.get("most_visited_zone")
    return JourneySummaryRead(
        total_visitors=s["total_visitors"],
        active_visitors=s["active_visitors"],
        avg_visit_duration_seconds=s["avg_visit_duration_seconds"],
        avg_zone_dwell_seconds=s["avg_zone_dwell_seconds"],
        total_zone_visits=s["total_zone_visits"],
        most_visited_zone=(
            MostVisitedZoneRead(
                zone_id=most["zone_id"], name=most["name"], visits=most["visits"]
            )
            if most
            else None
        ),
    )


@router.get("", response_model=JourneyListRead)
def list_journeys(
    store_id: UUID,
    camera_id: Optional[UUID] = None,
    zone_id: Optional[UUID] = None,
    start: Optional[datetime] = Query(default=None),
    end: Optional[datetime] = Query(default=None),
    confidence: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Paged anonymous journeys for one store."""
    items, total = _svc(db).list_journeys(
        store_id=store_id,
        camera_id=camera_id,
        zone_id=zone_id,
        start=start,
        end=end,
        confidence=confidence,
        limit=limit,
        offset=offset,
    )
    return JourneyListRead(
        items=[_item(i) for i in items],
        total=total,
    )


@router.get("/{global_person_id}", response_model=JourneyDetailRead)
def get_journey(
    global_person_id: str,
    store_id: UUID,
    db: Session = Depends(get_db),
):
    """Full timeline of one anonymous journey."""
    detail = _svc(db).get_journey(store_id=store_id, global_person_id=global_person_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Journey not found")
    item = _item(detail).model_dump()
    return JourneyDetailRead(
        **item,
        track_associations=[
            TrackAssociationRead(**a) for a in detail["track_associations"]
        ],
        zone_visits=[ZoneVisitRead(**v) for v in detail["zone_visits"]],
        transitions=[TransitionRead(**t) for t in detail["transitions"]],
        timeline=[TimelineEventRead(**e) for e in detail["timeline"]],
    )


def _item(d: dict):
    """Map a service journey dict onto the flat JourneyItemRead fields."""
    return JourneyItemRead(
        global_person_id=d["global_person_id"],
        store_id=d["store_id"],
        status=d["status"],
        confidence=d["confidence"],
        first_seen_at=d["first_seen_at"],
        last_seen_at=d["last_seen_at"],
        duration_seconds=d["duration_seconds"],
        camera_count=d["camera_count"],
        cameras_visited=[CameraVisitedRead(**c) for c in d["cameras_visited"]],
        zone_visits_total=d["zone_visits_total"],
        zones_visited=[ZoneVisitedRead(**z) for z in d["zones_visited"]],
    )