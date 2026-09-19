"""Shelf snapshot entity (M30 — periodic shelf occupancy monitoring).

A `ShelfSnapshot` is one periodic AI observation of a SINGLE configured shelf
region on a camera (e.g. "Shelf 2 is 61% full, MEDIUM, 12 products visible").

Architecture (M30): the edge runtime keeps the live loop cheap (person
tracking only). On a wall-clock cadence (`shelf_snapshot_interval_seconds`,
default 30s) it runs product YOLO on one frame, computes per-region occupancy
from product-box coverage, checks whether a person occludes each region, and
writes one `ShelfSnapshot` row per region. The full-frame and per-region JPEG
crops are stored on disk under `SHELF_SNAPSHOT_DIR` (NEVER in PostgreSQL — same
rule as intake photos). Rows are retained for `SHELF_SNAPSHOT_RETENTION_DAYS`.

Like every AI output, this is an OBSERVATION, not business truth: it never
mutates inventory, batches, planogram data, or the `shelves` table.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin

# Fill-ratio status (independent of the read-time ShelfIntelligence labels —
# these describe a snapshot, not a 24h window).
SNAPSHOT_EMPTY = "EMPTY"
SNAPSHOT_LOW = "LOW"
SNAPSHOT_MEDIUM = "MEDIUM"
SNAPSHOT_FULL = "FULL"

VALID_SNAPSHOT_STATUSES = {SNAPSHOT_EMPTY, SNAPSHOT_LOW, SNAPSHOT_MEDIUM, SNAPSHOT_FULL}


class ShelfSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "shelf_snapshots"
    __table_args__ = (
        # History/trend lookups are always (store, camera, shelf_code, time).
        Index(
            "ix_shelf_snapshots_store_camera_shelf_observed",
            "store_id",
            "camera_id",
            "shelf_code",
            "observed_at",
        ),
    )

    store_id = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    camera_id = mapped_column(
        ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Configured region identity (mirrors `camera.config.shelf_regions`).
    shelf_code: Mapped[str] = mapped_column(String(30), nullable=False)  # e.g. "S1"
    shelf_label: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    region_bbox: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)  # [x1,y1,x2,y2]

    # On-disk snapshot files (relative to SHELF_SNAPSHOT_DIR). The region crop
    # may be NULL when the region is tiny/empty today; the full-frame file is
    # always written so an operator can review the raw view.
    snapshot_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    crop_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    fill_percentage: Mapped[float] = mapped_column(Float, nullable=False)  # 0.0..100.0
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # EMPTY/LOW/MEDIUM/FULL
    product_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Occlusion: a tracked person overlay the region when the snapshot was
    # taken. When True, the fill must NOT be trusted as official stock state;
    # the UI shows it as "occluded — person blocking shelf".
    occluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    occlusion_note: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    store = relationship("Store")
    camera = relationship("Camera")