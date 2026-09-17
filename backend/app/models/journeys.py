"""M19 — Anonymous Customer Journeys (PostgreSQL).

These four tables capture cross-camera *anonymous* person continuity and zone
behaviour:

* global_person_sessions      — one row per anonymous Global Person ID.
* person_track_associations   — which local (camera, track) belonged to which
                                global session, and for how long.
* zone_visits                 — enter/exit (+ dwell) of an anonymous visitor in
                                a physical store zone.
* person_camera_transitions   — a global person appearing on a new camera.

PRIVACY
-------
There is deliberately NO identity here. `global_person_id` is an opaque,
store-scoped UUID that maps ONLY to camera-local track ids. No names, no face
images, no biometric or demographic data, and crucially NO embeddings (Re-ID
embeddings live only in process memory — test case N proves nothing is stored).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin

# Confidence labels (mirror reid.models.Confidence values).
CONF_HIGH = "HIGH"
CONF_MEDIUM = "MEDIUM"
CONF_LOW = "LOW"
CONF_UNKNOWN = "UNKNOWN"
VALID_CONFIDENCES = {CONF_HIGH, CONF_MEDIUM, CONF_LOW, CONF_UNKNOWN}

SESSION_ACTIVE = "active"
SESSION_EXPIRED = "expired"


class GlobalPersonSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "global_person_sessions"
    __table_args__ = (
        UniqueConstraint(
            "store_id", "global_person_id", name="uq_global_person_sessions_store_global"
        ),
    )

    store_id = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    global_person_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default=SESSION_ACTIVE, nullable=False)
    confidence: Mapped[str] = mapped_column(String(20), default=CONF_UNKNOWN, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    camera_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    store = relationship("Store")


class PersonTrackAssociation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "person_track_associations"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "camera_id",
            "track_id",
            name="uq_person_track_associations_session_camera_track",
        ),
        Index("ix_person_track_associations_camera_track", "camera_id", "track_id"),
    )

    store_id = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id = mapped_column(
        ForeignKey("global_person_sessions.id", ondelete="CASCADE"), nullable=False
    )
    global_person_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    camera_id = mapped_column(
        ForeignKey("cameras.id", ondelete="SET NULL"), nullable=False, index=True
    )
    # Camera-LOCAL tracking id — NEVER overwritten, stays as ByteTrack produced it.
    track_id: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confidence: Mapped[str] = mapped_column(String(20), default=CONF_UNKNOWN, nullable=False)

    store = relationship("Store")
    session = relationship("GlobalPersonSession", backref="track_associations")
    camera = relationship("Camera")


class ZoneVisit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "zone_visits"

    store_id = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    global_person_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    session_id = mapped_column(
        ForeignKey("global_person_sessions.id", ondelete="CASCADE"), nullable=True
    )
    zone_id = mapped_column(
        ForeignKey("zones.id", ondelete="CASCADE"), nullable=False, index=True
    )
    camera_id = mapped_column(
        ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True, index=True
    )
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    exited_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    dwell_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence: Mapped[str] = mapped_column(String(20), default=CONF_UNKNOWN, nullable=False)

    store = relationship("Store")
    session = relationship("GlobalPersonSession", backref="zone_visits")
    zone = relationship("Zone")
    camera = relationship("Camera")


class PersonCameraTransition(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "person_camera_transitions"

    store_id = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    global_person_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    session_id = mapped_column(
        ForeignKey("global_person_sessions.id", ondelete="CASCADE"), nullable=True
    )
    from_camera_id = mapped_column(
        ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True, index=True
    )
    to_camera_id = mapped_column(
        ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True, index=True
    )
    transitioned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    time_gap_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence: Mapped[str] = mapped_column(String(20), default=CONF_UNKNOWN, nullable=False)

    store = relationship("Store")
    session = relationship("GlobalPersonSession", backref="transitions")