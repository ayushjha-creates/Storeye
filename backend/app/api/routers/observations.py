"""AI Observations API routes.

AI RULE
-------
AI observations are OBSERVATIONAL facts about what the store "saw". They
MUST NOT change inventory or create batches automatically. This router only
persists and exposes observations; all record/query logic goes through
ObservationService. A recorded observation never mutates inventory.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..authz import effective_store_id, require_same_store, scoped_get
from ..deps import get_db, require_role
from ...models import Observation, User
from ...schemas import (
    ActivityBucket,
    ObservationCreate,
    ObservationList,
    ObservationRead,
    ObservationSummary,
)
from ...services.observations import ObservationService

router = APIRouter(prefix="/observations", tags=["observations"])


@router.post(
    "", response_model=ObservationRead, status_code=status.HTTP_201_CREATED
)
def create_observation(
    payload: ObservationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    require_same_store(current_user, payload.store_id)
    svc = ObservationService(db)
    obs = svc.record_observation(
        observation_type=payload.observation_type,
        store_id=payload.store_id,
        camera_id=payload.camera_id,
        product_id=payload.product_id,
        batch_id=payload.batch_id,
        track_id=payload.track_id,
        frame_number=payload.frame_number,
        source=payload.source,
        confidence=payload.confidence,
        bbox=payload.bbox,
        text=payload.text,
        source_observation_id=payload.source_observation_id,
        observed_at=payload.observed_at,
        details=payload.details,
    )
    return ObservationRead.model_validate(obs)


@router.get("", response_model=ObservationList)
def list_observations(
    store_id: Optional[UUID] = None,
    camera_id: Optional[UUID] = None,
    product_id: Optional[UUID] = None,
    observation_type: Optional[str] = Query(
        default=None, description="Filter by observation type"
    ),
    confidence_min: Optional[float] = Query(
        default=None, ge=0.0, le=1.0, description="Minimum confidence"
    ),
    from_: Optional[datetime] = Query(
        default=None, alias="from", description="Inclusive window start (UTC)"
    ),
    to: Optional[datetime] = Query(
        default=None, description="Inclusive window end (UTC)"
    ),
    class_name: Optional[str] = Query(
        default=None,
        description="PRODUCT AI class label (details.class_name), e.g. Complan; "
        "use for unmapped-class history",
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    """Paged observation list.

    Filters and pagination are evaluated in PostgreSQL; `total` is the full
    match count (independent of offset/limit) so the UI can paginate
    correctly. Read-only: never mutates inventory or batches.
    """
    sid = effective_store_id(current_user, store_id)
    svc = ObservationService(db)
    items, total = svc.query_observations(
        store_id=sid,
        camera_id=camera_id,
        product_id=product_id,
        observation_type=observation_type,
        confidence_min=confidence_min,
        start=from_,
        end=to,
        class_name=class_name,
        limit=limit,
        offset=offset,
    )
    return ObservationList(
        items=[ObservationRead.model_validate(i) for i in items],
        total=total,
    )


@router.get("/summary", response_model=ObservationSummary)
def observation_summary(
    store_id: Optional[UUID] = None,
    camera_id: Optional[UUID] = None,
    product_id: Optional[UUID] = None,
    observation_type: Optional[str] = Query(
        default=None, description="Restrict aggregation to one observation type"
    ),
    confidence_min: Optional[float] = Query(
        default=None, ge=0.0, le=1.0, description="Minimum confidence"
    ),
    class_name: Optional[str] = Query(
        default=None,
        description="PRODUCT AI class label (details.class_name) to restrict to",
    ),
    hours: int = Query(default=24, ge=1, le=168, description="Look-back window"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    """Aggregate a bounded observation window for analytics panels.

    Returns per-type counts, distinct tracked people (PERSON observations),
    average confidence, last-seen timestamp and time-bucketed activity.
    Pure read aggregation over PostgreSQL; nothing is mutated.
    """
    sid = effective_store_id(current_user, store_id)
    svc = ObservationService(db)
    summary = svc.observation_summary(
        store_id=sid,
        camera_id=camera_id,
        product_id=product_id,
        observation_type=observation_type,
        confidence_min=confidence_min,
        hours=hours,
        class_name=class_name,
    )
    return ObservationSummary(
        total=summary["total"],
        by_type=summary["by_type"],
        distinct_tracks=summary["distinct_tracks"],
        avg_confidence=summary["avg_confidence"],
        last_observed_at=summary["last_observed_at"],
        activity=[
            ActivityBucket(bucket_ts=item.bucket_ts, count=item.count)
            for item in summary["activity"]
        ],
    )


@router.get("/{obs_id}", response_model=ObservationRead)
def get_observation(
    obs_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("STAFF")),
):
    return ObservationRead.model_validate(scoped_get(db, current_user, Observation, obs_id))
