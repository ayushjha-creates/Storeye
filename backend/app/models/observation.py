"""Storeye AI Observation entity.

Architectural rule:
    AI OBSERVATION != BUSINESS TRUTH

AI systems (YOLO person/shelf detection, ByteTrack tracking, PaddleOCR,
the expiry parser) produce OBSERVATIONS about the world. These records are
what the store "saw", NOT what the inventory is. Recording an observation
MUST never change inventory or auto-create batches — those remain explicit
business operations (see app.services.inventory).

PRIVACY
    Person tracking is anonymous. We store an opaque, session-scoped
    `track_id` only. We NEVER store face embeddings, face images, names,
    or biometric/identity data. A track_id from one video/session does NOT
    identify the same person across sessions.

FLEXIBILITY
    `metadata` is PostgreSQL JSONB for observation-type-specific extras
    (e.g. expiry fields, parser warnings, class id/name) without opening a
    new column for every case. Unrelated business state is NOT stored here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin

# Observation discriminator values.
OBS_PERSON = "PERSON"
OBS_PRODUCT = "PRODUCT"
OBS_TEXT = "TEXT"
OBS_EXPIRY_METADATA = "EXPIRY_METADATA"

VALID_OBSERVATION_TYPES = {OBS_PERSON, OBS_PRODUCT, OBS_TEXT, OBS_EXPIRY_METADATA}


class Observation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "observations"

    # Discriminator. Use VALID_OBSERVATION_TYPES values.
    observation_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)

    # Optional associations — observations may predate any store/camera/
    # product/batch linkage, so all are nullable.
    store_id = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=True, index=True
    )
    camera_id = mapped_column(
        ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True, index=True
    )
    product_id = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    batch_id = mapped_column(
        ForeignKey("batches.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Anonymous, session-scoped track id (people). Never identity.
    track_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    # Frame of the source media (0-based). NULL if unknown.
    frame_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Free-form source identifier, e.g. a path to a test video/file or a
    # device label. Raw video is NEVER stored in PostgreSQL.
    source: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # [x1, y1, x2, y2] pixel coordinates, as JSONB.
    bbox: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Human/raw text captured (e.g. OCR text or parser raw_text).
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Link to the observation this one was derived from (e.g. an
    # EXPIRY_METADATA observation referencing the TEXT observation).
    source_observation_id = mapped_column(
        ForeignKey("observations.id", ondelete="SET NULL"), nullable=True, index=True
    )

    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # Flexible, observation-type-specific extras (JSONB). Avoids the reserved
    # `metadata` name on DeclarativeBase.
    details: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    store = relationship("Store")
    camera = relationship("Camera")
    product = relationship("Product")
    source_observation = relationship("Observation", remote_side="Observation.id")