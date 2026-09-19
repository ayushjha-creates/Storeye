"""Pydantic schemas for Anonymous Customer Journeys (M19).

Everything here is keyed by an OPAQUE `global_person_id` and carries NO
identity: no names, no face images, no biometrics, no embeddings, no crops.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class CameraVisitedRead(BaseModel):
    camera_id: UUID
    name: Optional[str] = None


class ZoneVisitedRead(BaseModel):
    zone_id: UUID
    name: Optional[str] = None
    visits: int = 0


class JourneyItemRead(BaseModel):
    global_person_id: str
    store_id: UUID
    status: str  # active | expired
    confidence: str  # HIGH | MEDIUM | LOW | UNKNOWN
    first_seen_at: datetime
    last_seen_at: datetime
    duration_seconds: float
    camera_count: int
    cameras_visited: List[CameraVisitedRead]
    zone_visits_total: int
    zones_visited: List[ZoneVisitedRead]


class JourneyListRead(BaseModel):
    items: List[JourneyItemRead]
    total: int


class TrackAssociationRead(BaseModel):
    camera_id: Optional[UUID]
    camera_name: Optional[str]
    track_id: int
    started_at: datetime
    ended_at: Optional[datetime]
    last_seen_at: datetime
    confidence: str


class ZoneVisitRead(BaseModel):
    zone_id: UUID
    zone_name: Optional[str]
    camera_id: Optional[UUID]
    camera_name: Optional[str]
    entered_at: datetime
    exited_at: Optional[datetime]
    dwell_seconds: Optional[float]
    confidence: str


class TransitionRead(BaseModel):
    from_camera_id: Optional[UUID]
    from_camera_name: Optional[str]
    to_camera_id: Optional[UUID]
    to_camera_name: Optional[str]
    transitioned_at: datetime
    time_gap_seconds: Optional[float]
    confidence: str


class TimelineEventRead(BaseModel):
    at: datetime
    type: str  # journey_start | track | zone_enter | zone_exit | transition
    camera_id: Optional[UUID]
    camera_name: Optional[str]
    zone_id: Optional[UUID]
    zone_name: Optional[str]
    detail: str


class JourneyDetailRead(JourneyItemRead):
    track_associations: List[TrackAssociationRead]
    zone_visits: List[ZoneVisitRead]
    transitions: List[TransitionRead]
    timeline: List[TimelineEventRead]


class MostVisitedZoneRead(BaseModel):
    zone_id: UUID
    name: Optional[str]
    visits: int


class JourneySummaryRead(BaseModel):
    total_visitors: int
    active_visitors: int
    avg_visit_duration_seconds: Optional[float]
    avg_zone_dwell_seconds: Optional[float]
    total_zone_visits: int
    most_visited_zone: Optional[MostVisitedZoneRead]


class DailyFootfallRead(BaseModel):
    date: date
    visitors: int


class DailyFootfallListRead(BaseModel):
    items: List[DailyFootfallRead]