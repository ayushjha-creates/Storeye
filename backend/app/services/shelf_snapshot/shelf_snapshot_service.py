"""M30 periodic shelf-occupancy persistence.

A `ShelfSnapshotService` owns the on-disk snapshot images AND the
`shelf_snapshots` rows behind them.

Disk policy (matches the M22 intake-photo rule): the JPEG files NEVER enter
PostgreSQL — the table stores only ROOT-RELATIVE paths, and every read is
path-traversal-guarded. Rows are written at the wall-clock snapshot cadence
(the worker deduplicates via the pipeline's cadence gate, so we write what the
pipeline emits, one row per region per scan). Retention sweeps both disk and
rows together via `SHELF_SNAPSHOT_RETENTION_DAYS`.

This service never mutates inventory, batches, planograms, or the `shelves`
table — snapshots are OBSERVATIONS, not stock truth.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import ShelfSnapshot
from ...models.shelf_snapshot import (
    SNAPSHOT_EMPTY,
    SNAPSHOT_LOW,
    SNAPSHOT_MEDIUM,
    SNAPSHOT_FULL,
    VALID_SNAPSHOT_STATUSES,
)
from ...db.base import gen_uuid

logger = logging.getLogger("storeye.shelf_snapshot")

try:  # cv2 is optional in pure-DB unit tests.
    import cv2
except Exception:  # pragma: no cover - defensive
    cv2 = None  # type: ignore


class ShelfSnapshotError(Exception):
    """Base error for shelf-snapshot persistence."""


class SnapshotNotFoundError(ShelfSnapshotError):
    """No snapshot row / file matched a request."""


def jpeg_encode(image) -> Optional[bytes]:
    """Encode a BGR frame as JPEG bytes; None when OpenCV is unavailable."""
    if cv2 is None or image is None:
        return None
    ok, buf = cv2.imencode(".jpg", image)
    return buf.tobytes() if ok else None


class ShelfSnapshotService:
    """Writes and serves periodic shelf-snapshot rows + images for one store."""

    # Purge stale rows/files once every N writes (bounded disk, cheap sweep).
    PURGE_EVERY_N_WRITES = 20

    def __init__(
        self,
        session: Session,
        root: Path,
        *,
        store_id: Optional[str] = None,
        camera_id: Optional[str] = None,
        retention_days: float = 7.0,
    ) -> None:
        self.session = session
        self.root = Path(root).resolve()
        self.store_id = store_id or ""
        self.camera_id = camera_id
        self.retention_days = float(retention_days)
        self._writes_since_purge = 0

    # -- writes ----------------------------------------------------------
    def write_snapshot(
        self,
        *,
        camera_id: str,
        observed_at: datetime,
        shelf_code: str,
        shelf_label: Optional[str] = None,
        region_bbox: Optional[list] = None,
        fill_percentage: float,
        status: str,
        product_count: int,
        occluded: bool,
        occlusion_note: Optional[str] = None,
        confidence: Optional[float] = None,
        frame_image=None,  # BGR numpy frame (optional; used for the JPEGs)
    ) -> ShelfSnapshot:
        """Persist one snapshot event. Files saved first, then the row.

        Returns the created ShelfSnapshot (id set immediately so the worker can
        count it). Raises ShelfSnapshotError when the session write fails.
        """
        if status not in VALID_SNAPSHOT_STATUSES:
            status = SNAPSHOT_EMPTY
        if not (0.0 <= fill_percentage <= 100.0):
            fill_percentage = max(0.0, min(fill_percentage, 100.0))

        snapshot_path = None
        crop_path = None
        width, height = 0, 0
        if frame_image is not None and getattr(frame_image, "ndim", 0) >= 2:
            height, width = frame_image.shape[:2]

        full_jpeg = jpeg_encode(frame_image) if frame_image is not None else None
        rel_dir = self._rel_dir(observed_at, camera_id)
        if full_jpeg is not None:
            snapshot_path = rel_dir / f"{self._ts(observed_at)}_{shelf_code}_full.jpg"
            self._save_bytes(snapshot_path, full_jpeg)
        crop = self._crop_region(frame_image, region_bbox, width, height)
        crop_jpeg = jpeg_encode(crop) if crop is not None else None
        if crop_jpeg is not None:
            crop_path = rel_dir / f"{self._ts(observed_at)}_{shelf_code}_crop.jpg"
            self._save_bytes(crop_path, crop_jpeg)

        row = ShelfSnapshot(
            id=gen_uuid(),
            store_id=self.store_id,
            camera_id=camera_id,
            shelf_code=shelf_code,
            shelf_label=shelf_label,
            region_bbox=region_bbox,
            snapshot_path=self._rel(snapshot_path),
            crop_path=self._rel(crop_path),
            fill_percentage=float(fill_percentage),
            status=status,
            product_count=int(product_count),
            occluded=bool(occluded),
            occlusion_note=occlusion_note,
            confidence=confidence,
            observed_at=observed_at,
        )
        self.session.add(row)
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        # Opportunistic retention sweep (bounded disk/rows); a failure never
        # kills the snapshot write itself.
        self._writes_since_purge += 1
        if self._writes_since_purge >= self.PURGE_EVERY_N_WRITES:
            self._writes_since_purge = 0
            try:
                self.purge_older_than(self.retention_days)
            except Exception:  # pragma: no cover - defensive
                logger.exception("Shelf snapshot retention sweep failed")
        return row

    # -- reads (path-guarded) --------------------------------------------
    def resolve_file(self, row: ShelfSnapshot) -> Path:
        """Resolve an on-disk snapshot image, guarded against traversal.

        Follows the M22 intake-photo rule: the resolved path must stay under
        the configured root.
        """
        rel = row.snapshot_path or row.crop_path
        if not rel:
            raise SnapshotNotFoundError("Snapshot has no stored image.")
        root = self.root
        candidate = (root / rel).resolve()
        if candidate != root and root not in candidate.parents:
            raise SnapshotNotFoundError("Snapshot path escapes the snapshot root.")
        if not candidate.is_file():
            raise SnapshotNotFoundError("Snapshot image is no longer on disk.")
        return candidate

    # -- retention -------------------------------------------------------
    def purge_older_than(self, retention_days: float) -> int:
        """Delete rows + files older than `retention_days`; returns rows removed.

        Only ever touches shelf_snapshots rows and their own on-disk images.
        """
        if retention_days <= 0:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=retention_days * 86400)
        rows = self.session.execute(
            select(ShelfSnapshot).where(ShelfSnapshot.observed_at < cutoff)
        ).scalars().all()
        for row in rows:
            for attr in ("snapshot_path", "crop_path"):
                rel = getattr(row, attr)
                if not rel:
                    continue
                try:
                    self._delete_rel(str(rel))
                except Exception:  # pragma: no cover - defensive
                    logger.exception("File removal failed for %s", rel)
            self.session.delete(row)
        self.session.commit()
        return len(rows)

    # -- internals -------------------------------------------------------
    @staticmethod
    def _ts(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).strftime("%H%M%S%f")

    def _rel_dir(self, observed_at: datetime, camera_id: str) -> Path:
        day = observed_at.astimezone(timezone.utc).strftime("%Y%m%d")
        return Path(camera_id) / day

    @staticmethod
    def _rel(p: Optional[Path]) -> Optional[str]:
        return p.as_posix() if p is not None else None

    def _save_bytes(self, rel: Path, data: bytes) -> None:
        full = self.root.joinpath(rel)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(data)

    def _delete_rel(self, rel: str) -> None:
        full = (self.root / rel).resolve()
        if self.root not in full.parents:
            return
        try:
            full.unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def _crop_region(image, region_bbox: Optional[list], width: int, height: int):
        """Pixel-crop a normalized region from the frame (M30 region crop)."""
        if image is None or not region_bbox or len(region_bbox) != 4:
            return None
        if width <= 0 or height <= 0:
            return None
        try:
            rx1 = max(0, min(int(round(float(region_bbox[0]) * width)), width - 1))
            ry1 = max(0, min(int(round(float(region_bbox[1]) * height)), height - 1))
            rx2 = max(rx1 + 1, min(int(round(float(region_bbox[2]) * width)), width))
            ry2 = max(ry1 + 1, min(int(round(float(region_bbox[3]) * height)), height))
            region = image[ry1:ry2, rx1:rx2]
            return region if region.size > 0 else None
        except Exception:  # pragma: no cover - defensive
            return None