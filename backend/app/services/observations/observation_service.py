"""ObservationService — record and query AI observations.

Every `record_*` and `query_*` runs against the injected SQLAlchemy Session.
Writes commit all-or-nothing. This service NEVER touches inventory or batch
creation — those are explicit business operations in app.services.inventory.

AI observations are facts about what the store "saw". They are not, and
must never be allowed to become, automatic inventory changes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional, Sequence
from uuid import UUID

from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session

from app.models import (
    Observation,
    OBS_PERSON,
    OBS_PRODUCT,
    OBS_TEXT,
    OBS_EXPIRY_METADATA,
    VALID_OBSERVATION_TYPES,
)
from .errors import ValidationError

# Lower/upper bound checks for confidence (0..1). Keep a small epsilon so
# float noise does not trip strict inequality checks.
_MIN_CONF = 0.0
_MAX_CONF = 1.0
_CONF_EPS = 1e-9


class ActivityItem:
    """One time-bucket of observation counts (label + count)."""

    __slots__ = ("bucket_ts", "count")

    def __init__(self, *, bucket_ts: datetime, count: int) -> None:
        self.bucket_ts = bucket_ts
        self.count = count


class ObservationService:
    """Persistence + query API for AI observations."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------
    def record_observation(
        self,
        *,
        observation_type: str,
        store_id: Optional[UUID] = None,
        camera_id: Optional[UUID] = None,
        product_id: Optional[UUID] = None,
        batch_id: Optional[UUID] = None,
        track_id: Optional[int] = None,
        frame_number: Optional[int] = None,
        source: Optional[str] = None,
        confidence: Optional[float] = None,
        bbox: Optional[Sequence[float]] = None,
        text: Optional[str] = None,
        observed_at: Optional[datetime] = None,
        details: Optional[dict] = None,
        source_observation_id: Optional[UUID] = None,
    ) -> Observation:
        """Validate + persist a single observation, committing atomically."""
        if observation_type not in VALID_OBSERVATION_TYPES:
            raise ValidationError(
                f"invalid observation_type: {observation_type!r}; "
                f"expected one of {sorted(VALID_OBSERVATION_TYPES)}"
            )
        self._validate_optional_fk(store_id, "store")
        self._validate_optional_fk(camera_id, "camera")
        self._validate_optional_fk(product_id, "product")
        self._validate_optional_fk(batch_id, "batch")
        self._validate_optional_fk(source_observation_id, "observation")

        if confidence is not None and not (
            _MIN_CONF - _CONF_EPS <= confidence <= _MAX_CONF + _CONF_EPS
        ):
            raise ValidationError(f"confidence must be in [0,1], got {confidence!r}")

        if bbox is not None:
            bb = list(bbox)
            if len(bb) < 4 or any(not isinstance(v, (int, float)) for v in bb):
                raise ValidationError(f"bbox must be >=4 numbers, got {bb!r}")

        if track_id is not None and int(track_id) < 0:
            raise ValidationError(f"negative track_id not allowed: {track_id!r}")

        obs = Observation(
            observation_type=observation_type,
            store_id=store_id,
            camera_id=camera_id,
            product_id=product_id,
            batch_id=batch_id,
            track_id=track_id,
            frame_number=frame_number,
            source=source,
            confidence=confidence,
            bbox=list(bbox) if bbox is not None else None,
            text=text,
            observed_at=observed_at or datetime.now(timezone.utc),
            details=details or None,
            source_observation_id=source_observation_id,
        )
        self.session.add(obs)
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        self.session.refresh(obs)
        return obs

    # ------------------------------------------------------------------
    # Type-specific helpers (thin wrappers, single commit each).
    # ------------------------------------------------------------------
    def record_product_observation(
        self,
        *,
        store_id: Optional[UUID],
        camera_id: Optional[UUID],
        product_id: Optional[UUID],
        confidence: float,
        bbox: Sequence[float],
        observed_at: Optional[datetime] = None,
        frame_number: Optional[int] = None,
        source: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> Observation:
        """Record a product/shelf sighting. product_id may be None when the
        detection is uncertain and product matching has not been established."""
        return self.record_observation(
            observation_type=OBS_PRODUCT,
            store_id=store_id,
            camera_id=camera_id,
            product_id=product_id,
            frame_number=frame_number,
            source=source,
            confidence=confidence,
            bbox=bbox,
            observed_at=observed_at,
            details=details,
        )

    def record_person_observation(
        self,
        *,
        store_id: Optional[UUID],
        camera_id: Optional[UUID],
        track_id: int,
        confidence: float,
        bbox: Sequence[float],
        observed_at: Optional[datetime] = None,
        frame_number: Optional[int] = None,
        source: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> Observation:
        """Record an anonymous, session-scoped person observation.

        track_id is opaque and session-scoped: track_id == 7 in one video is
        NOT the same person as track_id == 7 in another session. No identity
        or biometric data is ever stored.
        """
        return self.record_observation(
            observation_type=OBS_PERSON,
            store_id=store_id,
            camera_id=camera_id,
            track_id=track_id,
            frame_number=frame_number,
            source=source,
            confidence=confidence,
            bbox=bbox,
            observed_at=observed_at,
            details=details,
        )

    def record_text_observation(
        self,
        *,
        store_id: Optional[UUID],
        camera_id: Optional[UUID],
        text: str,
        confidence: Optional[float],
        bbox: Optional[Sequence[float]],
        observed_at: Optional[datetime] = None,
        frame_number: Optional[int] = None,
        source: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> Observation:
        """Record OCR text (e.g. the raw text PaddleOCR produced)."""
        return self.record_observation(
            observation_type=OBS_TEXT,
            store_id=store_id,
            camera_id=camera_id,
            frame_number=frame_number,
            source=source,
            confidence=confidence,
            bbox=bbox,
            text=text,
            observed_at=observed_at,
            details=details,
        )

    def record_expiry_metadata_observation(
        self,
        *,
        store_id: Optional[UUID],
        source_observation_id: Optional[UUID] = None,
        raw_text: str,
        confidence: Optional[float],
        expiry_date: Any = None,
        expiry_date_precision: Optional[str] = None,
        manufacturing_date: Any = None,
        batch_number: Optional[str] = None,
        mrp: Any = None,
        warnings: Optional[Sequence[str]] = None,
        observed_at: Optional[datetime] = None,
        source: Optional[str] = None,
        camera_id: Optional[UUID] = None,
        product_id: Optional[UUID] = None,
        details_extra: Optional[dict] = None,
    ) -> Observation:
        """Record parsed product metadata as a fact.

        This NEVER creates or updates a Batch. Batch creation is an explicit
        business operation (BatchService.create_batch). Here we only persist
        that the expiry parser observed this metadata.

        `product_id` and `details_extra` let the camera OCR path attach a
        conservatively-matched catalog product (name/price) to the read. They
        are optional and never fabricate a match.
        """
        details: dict = {}
        if expiry_date is not None:
            details["expiry_date"] = str(expiry_date)
        if expiry_date_precision is not None:
            details["expiry_date_precision"] = expiry_date_precision
        if manufacturing_date is not None:
            details["manufacturing_date"] = str(manufacturing_date)
        if batch_number is not None:
            details["batch_number"] = batch_number
        if mrp is not None:
            details["mrp"] = str(mrp)
        if warnings:
            details["warnings"] = list(warnings)
        for key, value in (details_extra or {}).items():
            if value is not None:
                details[key] = value

        return self.record_observation(
            observation_type=OBS_EXPIRY_METADATA,
            store_id=store_id,
            camera_id=camera_id,
            product_id=product_id,
            source=source,
            confidence=confidence,
            text=raw_text,
            observed_at=observed_at,
            details=details or None,
            source_observation_id=source_observation_id,
        )

    # ------------------------------------------------------------------
    # Queries (simple, no analytics).
    # ------------------------------------------------------------------
    def _stmt(self) -> Any:
        return select(Observation)

    @staticmethod
    def _order_by_observed(stmt: Any, desc: bool) -> Any:
        col = Observation.observed_at
        return stmt.order_by(col.desc() if desc else col.asc())

    def get_observation(self, obs_id: UUID) -> Optional[Observation]:
        return self.session.get(Observation, obs_id)

    def observations_for_store(self, store_id: UUID) -> list[Observation]:
        return list(
            self.session.scalars(
                self._order_by_observed(
                    self._stmt().where(Observation.store_id == store_id), desc=True
                )
            )
        )

    def observations_for_camera(self, camera_id: UUID) -> list[Observation]:
        return list(
            self.session.scalars(
                self._order_by_observed(
                    self._stmt().where(Observation.camera_id == camera_id), desc=True
                )
            )
        )

    def observations_by_type(self, observation_type: str) -> list[Observation]:
        if observation_type not in VALID_OBSERVATION_TYPES:
            raise ValidationError(f"invalid observation_type: {observation_type!r}")
        return list(
            self.session.scalars(
                self._order_by_observed(
                    self._stmt().where(Observation.observation_type == observation_type),
                    desc=True,
                )
            )
        )

    def observations_for_product(self, product_id: UUID) -> list[Observation]:
        return list(
            self.session.scalars(
                self._order_by_observed(
                    self._stmt().where(Observation.product_id == product_id), desc=True
                )
            )
        )

    def observations_for_track(self, track_id: int) -> list[Observation]:
        return list(
            self.session.scalars(
                self._order_by_observed(
                    self._stmt().where(Observation.track_id == track_id), desc=True
                )
            )
        )

    def observations_for_time_range(
        self, start: datetime, end: datetime
    ) -> list[Observation]:
        return list(
            self.session.scalars(
                self._order_by_observed(
                    self._stmt().where(
                        Observation.observed_at >= start,
                        Observation.observed_at <= end,
                    ),
                    desc=False,
                )
            )
        )

    # ------------------------------------------------------------------
    # Analytics queries (server-side filters, pagination, aggregations).
    # These only READ observations; they never mutate business state.
    # ------------------------------------------------------------------
    @staticmethod
    def _filters(
        *,
        store_id: Optional[UUID],
        camera_id: Optional[UUID],
        product_id: Optional[UUID],
        observation_type: Optional[str],
        confidence_min: Optional[float],
        start: Optional[datetime],
        end: Optional[datetime],
        class_name: Optional[str] = None,
    ) -> list[Any]:
        if observation_type is not None and observation_type not in VALID_OBSERVATION_TYPES:
            raise ValidationError(
                f"invalid observation_type: {observation_type!r}; "
                f"expected one of {sorted(VALID_OBSERVATION_TYPES)}"
            )
        conds: list[Any] = []
        if store_id is not None:
            conds.append(Observation.store_id == store_id)
        if camera_id is not None:
            conds.append(Observation.camera_id == camera_id)
        if product_id is not None:
            conds.append(Observation.product_id == product_id)
        if observation_type is not None:
            conds.append(Observation.observation_type == observation_type)
        if confidence_min is not None:
            conds.append(Observation.confidence >= confidence_min)
        if start is not None:
            conds.append(Observation.observed_at >= start)
        if end is not None:
            conds.append(Observation.observed_at <= end)
        if class_name is not None:
            conds.append(
                Observation.details["class_name"].astext == class_name
            )
        return conds

    def query_observations(
        self,
        *,
        store_id: Optional[UUID] = None,
        camera_id: Optional[UUID] = None,
        product_id: Optional[UUID] = None,
        observation_type: Optional[str] = None,
        confidence_min: Optional[float] = None,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
        class_name: Optional[str] = None,
    ) -> tuple[list[Observation], int]:
        """Paged observation query. Filters run in PostgreSQL (no in-memory
        filtering). Returns (items, total_matches) where total_matches is the
        count of rows matching the filters, independent of offset/limit."""
        conds = self._filters(
            store_id=store_id,
            camera_id=camera_id,
            product_id=product_id,
            observation_type=observation_type,
            confidence_min=confidence_min,
            start=start,
            end=end,
            class_name=class_name,
        )
        total = (
            self.session.scalar(
                select(func.count()).select_from(Observation).where(*conds)
            )
            or 0
        )
        stmt = (
            select(Observation)
            .where(*conds)
            .order_by(Observation.observed_at.desc(), Observation.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(stmt)), total

    def observation_summary(
        self,
        *,
        store_id: Optional[UUID] = None,
        camera_id: Optional[UUID] = None,
        product_id: Optional[UUID] = None,
        observation_type: Optional[str] = None,
        confidence_min: Optional[float] = None,
        hours: int = 24,
        class_name: Optional[str] = None,
    ) -> dict:
        """Aggregate a bounded window of observations for analytics panels.

        The window is [now - hours, now] in UTC. Buckets are hourly for
        windows <= 24h and daily beyond. Pure read aggregation."""
        hours = min(max(int(hours), 1), 24 * 7)
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=hours)

        conds = self._filters(
            store_id=store_id,
            camera_id=camera_id,
            product_id=product_id,
            observation_type=observation_type,
            confidence_min=confidence_min,
            start=start,
            end=end,
            class_name=class_name,
        )

        total = (
            self.session.scalar(
                select(func.count()).select_from(Observation).where(*conds)
            )
            or 0
        )

        by_type = {
            r[0]: r[1]
            for r in self.session.execute(
                select(Observation.observation_type, func.count())
                .where(*conds)
                .group_by(Observation.observation_type)
            ).all()
        }

        distinct_tracks = (
            self.session.scalar(
                select(func.count(func.distinct(Observation.track_id))).where(
                    *conds,
                    Observation.track_id.is_not(None),
                )
            )
            or 0
        )

        avg_confidence = self.session.scalar(
            select(func.avg(Observation.confidence)).where(*conds)
        )

        last_observed_at = self.session.scalar(
            select(func.max(Observation.observed_at)).where(*conds)
        )

        bucket_seconds = 3600 if hours <= 24 else 86400
        bucket_no = func.floor(
            func.extract("epoch", Observation.observed_at) / bucket_seconds
        ).cast(Integer)
        trunk = func.to_timestamp(bucket_no * bucket_seconds)
        activity = [
            (r[0], r[1])
            for r in self.session.execute(
                select(trunk.label("bucket"), func.count())
                .where(*conds)
                .group_by("bucket")
                .order_by("bucket")
            ).all()
        ]
        counts = {bucket: count for bucket, count in activity}

        buckets: list[ActivityItem] = []
        start_epoch = int(start.timestamp() // bucket_seconds) * bucket_seconds
        current = start_epoch
        while current <= int(end.timestamp()):
            bucket_dt = datetime.fromtimestamp(current, tz=timezone.utc)
            buckets.append(ActivityItem(bucket_ts=bucket_dt, count=counts.get(bucket_dt, 0)))
            current += bucket_seconds

        return {
            "total": total,
            "by_type": by_type,
            "distinct_tracks": distinct_tracks,
            "avg_confidence": float(avg_confidence) if avg_confidence is not None else None,
            "last_observed_at": last_observed_at,
            "activity": buckets,
        }

    # ------------------------------------------------------------------
    # Retention (M29)
    # ------------------------------------------------------------------
    def purge_person_observations(
        self,
        *,
        store_id: UUID,
        retention_hours: int = 24,
        now: Optional[datetime] = None,
    ) -> int:
        """Delete PER-FRAME PERSON observation rows older than the diagnostic
        window. This is the M29 "no per-frame person history forever" guard:
        the hot person cache + journey aggregates carry the analytics; PERSON
        observation rows are at most a short debugging window.

        NEVER touches PRODUCT/TEXT/EXPIRY_METADATA observations and never
        touches any business table. Returns the number of rows deleted.
        """
        if retention_hours < 1:
            raise ValueError("retention_hours must be >= 1")
        cutoff = (now or datetime.now(timezone.utc)) - timedelta(
            hours=int(retention_hours)
        )
        result = self.session.execute(
            Observation.__table__.delete().where(
                Observation.store_id == store_id,
                Observation.observation_type == OBS_PERSON,
                Observation.observed_at < cutoff,
            )
        )
        self.session.commit()
        return result.rowcount or 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _validate_optional_fk(self, value: Optional[UUID], kind: str) -> None:
        """Only validates *shape* of the id if provided. Actual row existence
        is enforced by the DB foreign key, so a bad UUID surfaces as an
        informative IntegrityError (committed atomically, rolled back)."""
        if value is None:
            return
        if not isinstance(value, (UUID, str)):
            raise ValidationError(
                f"{kind}_id must be a UUID or None, got {type(value).__name__}"
            )