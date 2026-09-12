"""Reconciliation result entity — AI observations vs. inventory.

RECONCILIATION PRODUCES RESULTS ONLY. It NEVER mutates inventory, creates
inventory movements, creates batches, or changes stock. Persistent business
state changes remain explicit, separate operations.

For every (store, product, camera) in an observation window we compare the
AI-observed product count against the recorded database quantity and store a
single ReconciliationResult row with a human-reviewable status.

STATUSES:
    MATCH               observed quantity == database quantity
    POSSIBLE_SURPLUS    observed quantity >  database quantity (diff > 0)
    POSSIBLE_SHORTAGE   observed quantity <  database quantity (diff < 0)
    REVIEW_REQUIRED     no reliable AI evidence to reconcile against
                        (e.g. zero supporting observations / no confidence)

`difference` = ai_observed_quantity - database_quantity (signed).
`confidence` is a DOCUMENTED HEURISTIC (mean detection confidence of the
observations used), never a model probability. When unreliable, it is NULL.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin

# Reconciliation status values.
REC_MATCH = "MATCH"
REC_SURPLUS = "POSSIBLE_SURPLUS"
REC_SHORTAGE = "POSSIBLE_SHORTAGE"
REC_REVIEW = "REVIEW_REQUIRED"

VALID_RECONCILIATION_STATUSES = {
    REC_MATCH,
    REC_SURPLUS,
    REC_SHORTAGE,
    REC_REVIEW,
}


class ReconciliationResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "reconciliation_results"

    store_id = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Camera-scoped by design: NULL when reconciliation is store-wide without a
    # specific camera. Cross-camera fusion is intentionally NOT performed.
    camera_id = mapped_column(
        ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True, index=True
    )

    observation_window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    observation_window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    database_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    ai_observed_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    difference: Mapped[int] = mapped_column(Integer, nullable=False)  # ai - database

    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)

    # Documented heuristic (mean detection confidence), NOT a probability.
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Supporting detail: counting rule, per-frame counts, avg confidence, notes.
    details: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    store = relationship("Store")
    product = relationship("Product")
    camera = relationship("Camera")