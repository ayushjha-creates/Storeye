"""JourneyService — anonymous customer journey persistence + analytics (M19).

Persistence side
----------------
The edge runtime's pipeline emits TRACK_ASSOC / ZONE_ENTER / ZONE_EXIT event
kinds; the ObservationWriter funnels them here. Every row is tied to an opaque
`global_person_id` — never to a real identity — and, for zone visits and
transitions, always carries the local `track_id`? No: the schema deliberately
records only the global id at the journey level; the local (camera, track) link
lives in `person_track_associations`, which preserves ByteTrack's original ids
unchanged.

Read side
---------
Pure-read PostgreSQL aggregations for /api/journeys, /api/journeys/{id},
/api/journeys/summary and /api/zones/{zone}.analytics. Reading never mutates
anything (except the informational `mark_expired_sessions` helper used by the
demo/seed layer and tests).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Camera,
    GlobalPersonSession,
    PersonCameraTransition,
    PersonTrackAssociation,
    Store,
    Zone,
    ZoneVisit,
)
from .reid.models import Confidence

_TIMEOUT_SECONDS = 1800.0


def _timeout_seconds() -> float:
    try:
        return float(get_settings().GLOBAL_PERSON_TIMEOUT_SECONDS)
    except Exception:  # pragma: no cover - defensive
        return _TIMEOUT_SECONDS


class JourneyService:
    """PostgreSQL persistence + analytics for anonymous customer journeys."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Persistence (called by the edge writer / seed / tests)
    # ------------------------------------------------------------------
    def ensure_global_person(
        self,
        *,
        store_id: UUID,
        global_person_id: str,
        timestamp: datetime,
        confidence: str = Confidence.UNKNOWN.value,
    ) -> GlobalPersonSession:
        """Create/refresh the session row for an anonymous Global Person ID."""
        self._validate_confidence(confidence)
        now = self._as_utc(timestamp)
        existing = self.session.scalar(
            select(GlobalPersonSession).where(
                GlobalPersonSession.store_id == store_id,
                GlobalPersonSession.global_person_id == global_person_id,
            )
        )
        timeout = _timeout_seconds()
        if existing is None:
            session = GlobalPersonSession(
                store_id=store_id,
                global_person_id=global_person_id,
                status="active",
                confidence=confidence,
                first_seen_at=now,
                last_seen_at=now,
                expires_at=now + timedelta(seconds=timeout),
                camera_count=1,
            )
            self.session.add(session)
            self.session.commit()
            self.session.refresh(session)
            return session

        if now > existing.last_seen_at:
            existing.last_seen_at = now
            existing.expires_at = now + timedelta(seconds=timeout)
            existing.status = "active"
            existing.confidence = confidence
            self.session.add(existing)
            self.session.commit()
            self.session.refresh(existing)
        return existing

    def upsert_track_association(
        self,
        *,
        store_id: UUID,
        global_person_id: str,
        camera_id: UUID,
        track_id: int,
        confidence: str,
        timestamp: datetime,
    ) -> Tuple[PersonTrackAssociation, GlobalPersonSession]:
        """Associate one local (camera, track) to a global session.

        LOCAL track ids are untouched — they stay exactly as ByteTrack
        produced them. Re-running with the same (session, camera, track)
        refreshes the row instead of duplicating it.
        """
        self._validate_confidence(confidence)
        session = self.ensure_global_person(
            store_id=store_id,
            global_person_id=global_person_id,
            timestamp=timestamp,
            confidence=confidence,
        )
        now = self._as_utc(timestamp)
        existing = self.session.scalar(
            select(PersonTrackAssociation).where(
                PersonTrackAssociation.session_id == session.id,
                PersonTrackAssociation.camera_id == camera_id,
                PersonTrackAssociation.track_id == track_id,
            )
        )
        if existing is None:
            assoc = PersonTrackAssociation(
                store_id=store_id,
                session_id=session.id,
                global_person_id=global_person_id,
                camera_id=camera_id,
                track_id=track_id,
                started_at=now,
                last_seen_at=now,
                confidence=confidence,
            )
            self.session.add(assoc)
            self.session.commit()
            self.session.refresh(assoc)
            return assoc, session

        existing.last_seen_at = max(existing.last_seen_at, now)
        existing.started_at = min(existing.started_at, now)
        existing.confidence = confidence
        existing.ended_at = None
        self.session.add(existing)
        self.session.commit()
        self.session.refresh(existing)
        return existing, session

    def record_transition(
        self,
        *,
        store_id: UUID,
        global_person_id: str,
        from_camera_id: Optional[UUID],
        to_camera_id: Optional[UUID],
        timestamp: datetime,
        confidence: str,
        time_gap_seconds: Optional[float] = None,
    ) -> PersonCameraTransition:
        """Record one camera transition for an anonymous global visitor."""
        self._validate_confidence(confidence)
        session = self.ensure_global_person(
            store_id=store_id,
            global_person_id=global_person_id,
            timestamp=timestamp,
            confidence=confidence,
        )
        transition = PersonCameraTransition(
            store_id=store_id,
            session_id=session.id,
            global_person_id=global_person_id,
            from_camera_id=from_camera_id,
            to_camera_id=to_camera_id,
            transitioned_at=self._as_utc(timestamp),
            time_gap_seconds=time_gap_seconds,
            confidence=confidence,
        )
        self.session.add(transition)
        self.session.commit()
        self.session.refresh(transition)
        return transition

    def open_zone_visit(
        self,
        *,
        store_id: UUID,
        global_person_id: str,
        zone_id: UUID,
        camera_id: Optional[UUID],
        timestamp: datetime,
        confidence: str,
    ) -> ZoneVisit:
        """Open a zone visit for a global visitor (idempotent while open)."""
        self._validate_confidence(confidence)
        now = self._as_utc(timestamp)
        session = self.ensure_global_person(
            store_id=store_id,
            global_person_id=global_person_id,
            timestamp=now,
            confidence=confidence,
        )
        open_visit = self.session.scalar(
            select(ZoneVisit)
            .where(
                ZoneVisit.session_id == session.id,
                ZoneVisit.zone_id == zone_id,
                ZoneVisit.exited_at.is_(None),
            )
            .order_by(ZoneVisit.entered_at.desc())
            .limit(1)
        )
        if open_visit is not None:
            return open_visit
        visit = ZoneVisit(
            store_id=store_id,
            global_person_id=global_person_id,
            session_id=session.id,
            zone_id=zone_id,
            camera_id=camera_id,
            entered_at=now,
            confidence=confidence,
        )
        self.session.add(visit)
        self.session.commit()
        self.session.refresh(visit)
        return visit

    def close_zone_visit(
        self,
        *,
        store_id: UUID,
        global_person_id: str,
        zone_id: UUID,
        timestamp: datetime,
    ) -> Optional[ZoneVisit]:
        """Close the latest open visit for (global, zone), computing dwell."""
        now = self._as_utc(timestamp)
        session = self.session.scalar(
            select(GlobalPersonSession).where(
                GlobalPersonSession.store_id == store_id,
                GlobalPersonSession.global_person_id == global_person_id,
            )
        )
        if session is None:
            return None
        visit = self.session.scalar(
            select(ZoneVisit)
            .where(
                ZoneVisit.session_id == session.id,
                ZoneVisit.zone_id == zone_id,
                ZoneVisit.exited_at.is_(None),
            )
            .order_by(ZoneVisit.entered_at.desc())
            .limit(1)
        )
        if visit is None:
            return None
        visit.exited_at = now
        dwell = (now - visit.entered_at).total_seconds()
        visit.dwell_seconds = max(0.0, dwell)
        self.session.add(visit)
        self.session.commit()
        self.session.refresh(visit)
        return visit

    def mark_expired_sessions(self, store_id: UUID, now: Optional[datetime] = None) -> int:
        """Flip sessions idle beyond the timeout to `expired` (informational)."""
        now = self._as_utc(now or datetime.now(timezone.utc))
        cutoff = now - timedelta(seconds=_timeout_seconds())
        rows = self.session.scalars(
            select(GlobalPersonSession).where(
                GlobalPersonSession.store_id == store_id,
                GlobalPersonSession.status != "expired",
                GlobalPersonSession.last_seen_at < cutoff,
            )
        ).all()
        for row in rows:
            row.status = "expired"
            self.session.add(row)
        if rows:
            self.session.commit()
        return len(rows)

    def purge_analytics(
        self,
        *,
        store_id: UUID,
        retention_days: int = 30,
        now: Optional[datetime] = None,
    ) -> dict:
        """M29 retention: delete only the MINIMAL durable analytics for visits
        that ended before the cutoff.

        Deletes (oldest first) PersonTrackAssociation -> PersonCameraTransition
        -> ZoneVisit -> GlobalPersonSession for this store. It NEVER touches
        observations, products, inventory, batches, bills, sales, cameras,
        zones or any other business table. Sessions are deleted by their
        `last_seen_at`; a session still active right now is never removed.
        """
        if retention_days < 1:
            raise ValueError("retention_days must be >= 1")
        cutoff = self._as_utc(now or datetime.now(timezone.utc)) - timedelta(
            days=int(retention_days)
        )
        counts = {"track_associations": 0, "transitions": 0, "zone_visits": 0, "sessions": 0}

        staged = self.session.scalars(
            select(GlobalPersonSession.id).where(
                GlobalPersonSession.store_id == store_id,
                GlobalPersonSession.last_seen_at < cutoff,
            )
        ).all()
        if not staged:
            return counts
        session_ids = list(staged)

        for cls, col, key in (
            (PersonTrackAssociation, PersonTrackAssociation.session_id, "track_associations"),
            (PersonCameraTransition, PersonCameraTransition.session_id, "transitions"),
            (ZoneVisit, ZoneVisit.session_id, "zone_visits"),
        ):
            counts[key] = self.session.execute(
                cls.__table__.delete().where(col.in_(session_ids))
            ).rowcount or 0

        counts["sessions"] = self.session.execute(
            GlobalPersonSession.__table__.delete().where(
                GlobalPersonSession.id.in_(session_ids)
            )
        ).rowcount or 0

        self.session.commit()
        return counts

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def list_journeys(
        self,
        *,
        store_id: UUID,
        camera_id: Optional[UUID] = None,
        zone_id: Optional[UUID] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        confidence: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[dict], int]:
        """Paged journey list for a store (filters run in PostgreSQL)."""
        if confidence is not None:
            self._validate_confidence(confidence)

        conds = [GlobalPersonSession.store_id == store_id]
        if camera_id is not None:
            conds.append(
                GlobalPersonSession.id.in_(
                    select(PersonTrackAssociation.session_id).where(
                        PersonTrackAssociation.camera_id == camera_id
                    )
                )
            )
        if zone_id is not None:
            conds.append(
                GlobalPersonSession.id.in_(
                    select(ZoneVisit.session_id).where(ZoneVisit.zone_id == zone_id)
                )
            )
        if confidence is not None:
            conds.append(GlobalPersonSession.confidence == confidence)
        if start is not None:
            conds.append(GlobalPersonSession.last_seen_at >= start)
        if end is not None:
            conds.append(GlobalPersonSession.first_seen_at <= end)

        total = self.session.scalar(
            select(func.count()).select_from(GlobalPersonSession).where(*conds)
        ) or 0
        rows = self.session.scalars(
            select(GlobalPersonSession)
            .where(*conds)
            .order_by(GlobalPersonSession.last_seen_at.desc())
            .limit(min(max(int(limit), 1), 1000))
            .offset(max(int(offset), 0))
        ).all()
        return [self._journey_item(s) for s in rows], total

    def get_journey(self, store_id: UUID, global_person_id: str) -> Optional[dict]:
        """Full journey detail (associations, visits, transitions, timeline)."""
        session = self.session.scalar(
            select(GlobalPersonSession).where(
                GlobalPersonSession.store_id == store_id,
                GlobalPersonSession.global_person_id == global_person_id,
            )
        )
        if session is None:
            return None
        item = self._journey_item(session)

        cam_names = self._camera_names(store_id)
        zone_names = self._zone_names(store_id)

        associations = self.session.scalars(
            select(PersonTrackAssociation)
            .where(PersonTrackAssociation.session_id == session.id)
            .order_by(PersonTrackAssociation.started_at)
        ).all()
        item["track_associations"] = [
            {
                "camera_id": str(a.camera_id) if a.camera_id else None,
                "camera_name": cam_names.get(str(a.camera_id)),
                "track_id": a.track_id,
                "started_at": a.started_at.isoformat(),
                "ended_at": a.ended_at.isoformat() if a.ended_at else None,
                "last_seen_at": a.last_seen_at.isoformat(),
                "confidence": a.confidence,
            }
            for a in associations
        ]

        visits = self.session.scalars(
            select(ZoneVisit)
            .where(ZoneVisit.session_id == session.id)
            .order_by(ZoneVisit.entered_at)
        ).all()
        item["zone_visits"] = [
            {
                "zone_id": str(v.zone_id),
                "zone_name": zone_names.get(str(v.zone_id)),
                "camera_id": str(v.camera_id) if v.camera_id else None,
                "camera_name": cam_names.get(str(v.camera_id)),
                "entered_at": v.entered_at.isoformat(),
                "exited_at": v.exited_at.isoformat() if v.exited_at else None,
                "dwell_seconds": v.dwell_seconds,
                "confidence": v.confidence,
            }
            for v in visits
        ]

        transitions = self.session.scalars(
            select(PersonCameraTransition)
            .where(PersonCameraTransition.session_id == session.id)
            .order_by(PersonCameraTransition.transitioned_at)
        ).all()
        item["transitions"] = [
            {
                "from_camera_id": str(t.from_camera_id) if t.from_camera_id else None,
                "from_camera_name": cam_names.get(str(t.from_camera_id)),
                "to_camera_id": str(t.to_camera_id) if t.to_camera_id else None,
                "to_camera_name": cam_names.get(str(t.to_camera_id)),
                "transitioned_at": t.transitioned_at.isoformat(),
                "time_gap_seconds": t.time_gap_seconds,
                "confidence": t.confidence,
            }
            for t in transitions
        ]

        item["timeline"] = self._build_timeline(
            session=session, associations=associations, visits=visits,
            transitions=transitions, cam_names=cam_names, zone_names=zone_names,
        )
        return item

    def journey_summary(
        self,
        store_id: UUID,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> dict:
        """Header KPIs for the Anonymous Customer Journey dashboard."""
        base = select(GlobalPersonSession).where(GlobalPersonSession.store_id == store_id)
        if start is not None:
            base = base.where(GlobalPersonSession.last_seen_at >= start)
        if end is not None:
            base = base.where(GlobalPersonSession.first_seen_at <= end)

        total = self.session.scalar(
            select(func.count()).select_from(base.subquery())
        ) or 0
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=_timeout_seconds())
        active = self.session.scalar(
            select(func.count()).select_from(
                base.where(GlobalPersonSession.last_seen_at >= cutoff).subquery()
            )
        ) or 0

        avg_base = select(
            func.avg(
                GlobalPersonSession.last_seen_at - GlobalPersonSession.first_seen_at
            )
        ).where(
            GlobalPersonSession.store_id == store_id,
            GlobalPersonSession.last_seen_at > GlobalPersonSession.first_seen_at,
        )
        if start is not None:
            avg_base = avg_base.where(GlobalPersonSession.last_seen_at >= start)
        if end is not None:
            avg_base = avg_base.where(GlobalPersonSession.first_seen_at <= end)

        avg_duration = self.session.scalar(avg_base)
        duration_seconds = (
            avg_duration.total_seconds() if avg_duration is not None else None
        )

        visit_base = select(ZoneVisit).where(ZoneVisit.store_id == store_id)
        if start is not None:
            visit_base = visit_base.where(ZoneVisit.entered_at >= start)
        if end is not None:
            visit_base = visit_base.where(ZoneVisit.entered_at <= end)
        total_zone_visits = self.session.scalar(
            select(func.count()).select_from(visit_base.subquery())
        ) or 0
        avg_dwell = self.session.scalar(
            select(func.avg(ZoneVisit.dwell_seconds)).where(
                ZoneVisit.store_id == store_id,
                ZoneVisit.dwell_seconds.is_not(None),
            )
        )

        most_visited = self.session.execute(
            select(ZoneVisit.zone_id, func.count().label("cnt"))
            .where(ZoneVisit.store_id == store_id)
            .group_by(ZoneVisit.zone_id)
            .order_by(func.count().desc())
            .limit(1)
        ).first()
        most_visited_zone = None
        if most_visited is not None:
            zone_names = self._zone_names(store_id)
            most_visited_zone = {
                "zone_id": str(most_visited[0]),
                "name": zone_names.get(str(most_visited[0])),
                "visits": int(most_visited[1]),
            }

        return {
            "total_visitors": total,
            "active_visitors": active,
            "avg_visit_duration_seconds": duration_seconds,
            "avg_zone_dwell_seconds": float(avg_dwell) if avg_dwell is not None else None,
            "total_zone_visits": total_zone_visits,
            "most_visited_zone": most_visited_zone,
        }

    def daily_visitors(self, store_id: UUID, days: int = 7) -> List[dict]:
        """Per-day unique-footfall series (UTC) for the trailing `days` days.

        One row per global person session counted on the day it was first
        seen, filling every day back to `today - (days - 1)` with 0s when no
        sessions started that day. Read-only. Ordered oldest → newest.
        """
        today = datetime.now(timezone.utc).date()
        start_dt = datetime.combine(
            today - timedelta(days=days - 1), datetime.min.time(), tzinfo=timezone.utc
        )
        rows = self.session.execute(
            select(GlobalPersonSession.first_seen_at)
            .where(
                GlobalPersonSession.store_id == store_id,
                GlobalPersonSession.first_seen_at >= start_dt,
            )
            .order_by(GlobalPersonSession.first_seen_at)
        ).scalars().all()

        per_day: Dict = {}
        for ts in rows:
            if ts.tzinfo is not None:
                day = ts.astimezone(timezone.utc).date()
            else:
                day = ts.date()
            per_day[day] = per_day.get(day, 0) + 1

        return [
            {"date": day, "visitors": per_day.get(day, 0)}
            for i in range(days)
            for day in [today - timedelta(days=days - 1 - i)]
        ]

    def zone_analytics(
        self,
        zone_id: UUID,
        store_id: Optional[UUID] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> Optional[dict]:
        """Per-zone analytics (visits, dwell, currently inside)."""
        zone = self.session.get(Zone, zone_id)
        if zone is None:
            return None

        visit_conds: List[Any] = [ZoneVisit.zone_id == zone_id]
        unique_conds: List[Any] = [ZoneVisit.zone_id == zone_id]
        if store_id is not None:
            visit_conds.append(ZoneVisit.store_id == store_id)
            unique_conds.append(ZoneVisit.store_id == store_id)
        if start is not None:
            visit_conds.append(ZoneVisit.entered_at >= start)
            unique_conds.append(ZoneVisit.entered_at >= start)
        if end is not None:
            visit_conds.append(ZoneVisit.entered_at <= end)
            unique_conds.append(ZoneVisit.entered_at <= end)

        total = self.session.scalar(
            select(func.count()).select_from(ZoneVisit).where(*visit_conds)
        ) or 0

        visits = self.session.scalars(
            select(ZoneVisit).where(*visit_conds).order_by(ZoneVisit.entered_at.desc())
        ).all()
        closed = [v for v in visits if v.dwell_seconds is not None]
        dwells = sorted(v.dwell_seconds for v in closed)
        open_visits = [v for v in visits if v.exited_at is None]

        visitors_unique = self.session.scalar(
            select(func.count(func.distinct(ZoneVisit.global_person_id))).where(*unique_conds)
        ) or 0

        def _p90(values: List[float]) -> Optional[float]:
            if not values:
                return None
            idx = min(len(values) - 1, int(round(0.9 * (len(values) - 1))))
            return values[idx]

        return {
            "zone_id": str(zone.id),
            "zone_name": zone.name,
            "store_id": str(zone.store_id),
            "period_start": start.isoformat() if start else None,
            "period_end": end.isoformat() if end else None,
            "visits_total": total,
            "visitors_unique": visitors_unique,
            "avg_dwell_seconds": (
                sum(dwells) / len(dwells) if dwells else None
            ),
            "max_dwell_seconds": max(dwells) if dwells else None,
            "p90_dwell_seconds": _p90(dwells),
            "currently_inside": len(open_visits),
            "most_recent_visit_at": (
                visits[0].entered_at.isoformat() if visits else None
            ),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _journey_item(self, session: GlobalPersonSession) -> dict:
        now = datetime.now(timezone.utc)
        effective = (
            "active"
            if session.last_seen_at >= now - timedelta(seconds=_timeout_seconds())
            else "expired"
        )
        cam_names = self._camera_names(session.store_id)
        zone_names = self._zone_names(session.store_id)

        cameras = (
            self.session.execute(
                select(Camera.id)
                .join(PersonTrackAssociation, PersonTrackAssociation.camera_id == Camera.id)
                .where(PersonTrackAssociation.session_id == session.id)
                .distinct()
            )
            .scalars()
            .all()
        )
        zones = self.session.execute(
            select(ZoneVisit.zone_id, func.count().label("cnt"))
            .where(ZoneVisit.session_id == session.id)
            .group_by(ZoneVisit.zone_id)
        ).all()

        return {
            "global_person_id": session.global_person_id,
            "store_id": str(session.store_id),
            "status": effective,
            "confidence": session.confidence,
            "first_seen_at": session.first_seen_at.isoformat(),
            "last_seen_at": session.last_seen_at.isoformat(),
            "duration_seconds": max(
                0.0, (session.last_seen_at - session.first_seen_at).total_seconds()
            ),
            "camera_count": len(cameras),
            "cameras_visited": [
                {"camera_id": str(c), "name": cam_names.get(str(c))} for c in cameras
            ],
            "zone_visits_total": sum(int(z[1]) for z in zones),
            "zones_visited": [
                {"zone_id": str(z[0]), "name": zone_names.get(str(z[0])), "visits": int(z[1])}
                for z in zones
            ],
        }

    def _build_timeline(
        self,
        *,
        session: GlobalPersonSession,
        associations: Sequence[PersonTrackAssociation],
        visits: Sequence[ZoneVisit],
        transitions: Sequence[PersonCameraTransition],
        cam_names: Dict[str, Optional[str]],
        zone_names: Dict[str, Optional[str]],
    ) -> List[dict]:
        events: List[dict] = [
            {
                "at": session.first_seen_at.isoformat(),
                "type": "journey_start",
                "camera_id": None,
                "camera_name": None,
                "zone_id": None,
                "zone_name": None,
                "detail": "Anonymous journey started",
            }
        ]
        for a in associations:
            events.append(
                {
                    "at": a.started_at.isoformat(),
                    "type": "track",
                    "camera_id": str(a.camera_id) if a.camera_id else None,
                    "camera_name": cam_names.get(str(a.camera_id)),
                    "zone_id": None,
                    "zone_name": None,
                    "detail": f"Track {a.track_id} on {cam_names.get(str(a.camera_id)) or 'camera'}",
                }
            )
        for v in visits:
            events.append(
                {
                    "at": v.entered_at.isoformat(),
                    "type": "zone_enter",
                    "camera_id": str(v.camera_id) if v.camera_id else None,
                    "camera_name": cam_names.get(str(v.camera_id)),
                    "zone_id": str(v.zone_id),
                    "zone_name": zone_names.get(str(v.zone_id)),
                    "detail": f"Entered {zone_names.get(str(v.zone_id)) or 'zone'}",
                }
            )
            if v.exited_at is not None:
                dwell = v.dwell_seconds
                events.append(
                    {
                        "at": v.exited_at.isoformat(),
                        "type": "zone_exit",
                        "camera_id": str(v.camera_id) if v.camera_id else None,
                        "camera_name": cam_names.get(str(v.camera_id)),
                        "zone_id": str(v.zone_id),
                        "zone_name": zone_names.get(str(v.zone_id)),
                        "detail": (
                            f"Left {zone_names.get(str(v.zone_id)) or 'zone'}"
                            + (f" after {int(round(dwell))}s" if dwell is not None else "")
                        ),
                    }
                )
        for t in transitions:
            events.append(
                {
                    "at": t.transitioned_at.isoformat(),
                    "type": "transition",
                    "camera_id": str(t.to_camera_id) if t.to_camera_id else None,
                    "camera_name": cam_names.get(str(t.to_camera_id)),
                    "zone_id": None,
                    "zone_name": None,
                    "detail": (
                        f"Moved to {cam_names.get(str(t.to_camera_id)) or 'another camera'}"
                    ),
                }
            )
        events.sort(key=lambda e: (e["at"]))
        return events

    def _camera_names(self, store_id: UUID) -> Dict[str, Optional[str]]:
        rows = self.session.execute(
            select(Camera.id, Camera.name).where(Camera.store_id == store_id)
        ).all()
        return {str(cid): name for cid, name in rows}

    def _zone_names(self, store_id: UUID) -> Dict[str, Optional[str]]:
        rows = self.session.execute(
            select(Zone.id, Zone.name).where(Zone.store_id == store_id)
        ).all()
        return {str(zid): name for zid, name in rows}

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _validate_confidence(self, confidence: str) -> None:
        from app.models import VALID_CONFIDENCES

        if confidence not in VALID_CONFIDENCES:
            raise ValueError(
                f"invalid confidence {confidence!r}; expected one of "
                f"{sorted(VALID_CONFIDENCES)}"
            )