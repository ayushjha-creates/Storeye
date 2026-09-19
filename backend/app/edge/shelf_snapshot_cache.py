"""M30 — Shelf-snapshot in-memory cache (Layer-A hot read path).

MIRRORS the PostgreSQL `shelf_snapshots` rows so the monitor card + history
APIs can be served from memory without a DB round-trip.  PostgreSQL remains
the authoritative store — the cache is purely a read-speed mirror; if a
lookup misses (restart, overflow, different store) the router falls back to
a normal DB query.

Design follows the M29 `PersonStateManager` pattern: thread-safe, bounded
LRU+TTL, store-scoped, ``public_stats()`` for edge diagnostics.

RETENTION
  * HOT: cache entries live at most ``ttl_seconds`` (default 86400 = 24h).
  * DURABLE: PostgreSQL rows are purged by ``ShelfSnapshotService``
    (``SHELF_SNAPSHOT_RETENTION_DAYS``).
  * DISK: JPEG files are purged alongside PG rows by the same sweep.

PRIVACY
  Keys are opaque store-scoped triplets; no faces/embeddings stored.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from uuid import UUID

logger = logging.getLogger("storeye.edge.shelf_cache")

RegionKey = Tuple[str, str, str]  # (store_id, camera_id, shelf_code)
SnapshotId = str  # UUID hex


class ShelfSnapshotCacheEntry:
    """Lightweight in-memory snapshot record (mirrors one DB row)."""

    __slots__ = (
        "id",
        "store_id",
        "camera_id",
        "shelf_code",
        "shelf_label",
        "fill_percentage",
        "status",
        "product_count",
        "occluded",
        "occlusion_note",
        "confidence",
        "has_image",
        "observed_at",
    )

    def __init__(self, *, row=None, **kwargs) -> None:
        if row is not None:
            self.id = str(row.id)
            self.store_id = str(row.store_id)
            self.camera_id = str(row.camera_id)
            self.shelf_code = row.shelf_code
            self.shelf_label = row.shelf_label
            self.fill_percentage = float(row.fill_percentage)
            self.status = row.status
            self.product_count = int(row.product_count)
            self.occluded = bool(row.occluded)
            self.occlusion_note = row.occlusion_note
            self.confidence = float(row.confidence) if row.confidence is not None else None
            self.has_image = bool(getattr(row, "snapshot_path", None) or getattr(row, "crop_path", None))
            self.observed_at = row.observed_at
            return
        for k in self.__slots__:
            setattr(self, k, kwargs.get(k))

    def to_read_dict(self) -> dict:
        return {
            "id": self.id,
            "store_id": self.store_id,
            "camera_id": self.camera_id,
            "shelf_code": self.shelf_code,
            "shelf_label": self.shelf_label,
            "fill_percentage": self.fill_percentage,
            "status": self.status,
            "product_count": self.product_count,
            "occluded": self.occluded,
            "occlusion_note": self.occlusion_note,
            "confidence": self.confidence,
            "has_image": self.has_image,
            "observed_at": self.observed_at.isoformat() if self.observed_at is not None else None,
            # Image paths are NOT mirrored (disk retention is DB-side); the
            # image endpoint falls back to PostgreSQL for the actual file.
            "region_bbox": None,
            "snapshot_path": None,
            "crop_path": None,
            "created_at": None,
        }


class ShelfSnapshotCache:
    """Thread-safe store-scoped LRU+TTL cache of shelf-snapshot entries.

    Created once per edge runtime (same lifetime as PersonStateManager).
    Each ``(store_id, camera_id, shelf_code)`` key holds a bounded deque of
    recent snapshots (for sparkline history); the latest entry is the hot
    ``/summary`` payload.
    """

    PURGE_EVERY_N_OPS = 200

    def __init__(
        self,
        *,
        store_id: Optional[str] = None,
        ttl_seconds: float = 86400.0,
        max_entries: int = 4096,
        per_region_history: int = 24,
    ) -> None:
        self.store_id = store_id
        self._ttl_seconds = float(ttl_seconds)
        self._max_entries = int(max_entries)
        self._per_region_history = int(per_region_history)
        self._data: OrderedDict[RegionKey, deque[ShelfSnapshotCacheEntry]] = OrderedDict()
        self._id_index: Dict[SnapshotId, RegionKey] = {}
        self._lock = threading.RLock()
        self._ops_since_purge = 0
        self._stats = {
            "cache_hits": 0,
            "cache_misses": 0,
            "cache_inserts": 0,
            "cache_evictions_ttl": 0,
            "cache_evictions_capacity": 0,
        }

    # ------------------------------------------------------------------
    # Write path (called after PG commit by the worker)
    # ------------------------------------------------------------------
    def put(self, row, *, store_id: Optional[str] = None) -> Optional[ShelfSnapshotCacheEntry]:
        sid = str(store_id or row.store_id)
        if self.store_id and sid != self.store_id:
            return None
        entry = ShelfSnapshotCacheEntry(row=row)
        key: RegionKey = (sid, entry.camera_id, entry.shelf_code)
        with self._lock:
            bucket = self._data.get(key)
            if bucket is None:
                bucket = deque(maxlen=self._per_region_history)
                self._data[key] = bucket
                self._data.move_to_end(key)
                self._stats["cache_inserts"] += 1
            else:
                self._data.move_to_end(key)
            bucket.appendleft(entry)
            self._id_index[entry.id] = key
            # Evict oldest bucket if over capacity.
            self._maybe_purge_capacity()
            return entry

    def put_many(self, rows, *, store_id: Optional[str] = None) -> int:
        count = 0
        for row in rows:
            if self.put(row, store_id=store_id) is not None:
                count += 1
        return count

    # ------------------------------------------------------------------
    # Read path (hot query helpers)
    # ------------------------------------------------------------------
    def latest(self, store_id: str, camera_id: str) -> Dict[str, ShelfSnapshotCacheEntry]:
        with self._lock:
            out: Dict[str, ShelfSnapshotCacheEntry] = {}
            for code_bucket, bucket in self._data.items():
                if code_bucket[0] == store_id and code_bucket[1] == camera_id and bucket:
                    out[code_bucket[2]] = bucket[0]
                    self._stats["cache_hits"] += 1
            return out

    def history(
        self, store_id: str, camera_id: str, shelf_code: str, limit: int = 24
    ) -> List[ShelfSnapshotCacheEntry]:
        key: RegionKey = (store_id, camera_id, shelf_code)
        with self._lock:
            bucket = self._data.get(key)
            if bucket is None:
                self._stats["cache_misses"] += 1
                return []
            self._stats["cache_hits"] += 1
            return list(bucket)[:limit]

    def trend(
        self, store_id: str, camera_id: str, limit: int = 48
    ) -> List[ShelfSnapshotCacheEntry]:
        with self._lock:
            out: List[ShelfSnapshotCacheEntry] = []
            for code_bucket, bucket in self._data.items():
                if code_bucket[0] == store_id and code_bucket[1] == camera_id:
                    out.extend(bucket)
            # Sort newest-first; trim to limit.
            out.sort(key=lambda e: e.observed_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
            self._stats["cache_hits" if out else "cache_misses"] += 1
            return out[:limit]

    def get_by_id(self, snapshot_id: str) -> Optional[ShelfSnapshotCacheEntry]:
        with self._lock:
            key = self._id_index.get(snapshot_id)
            if key is None:
                self._stats["cache_misses"] += 1
                return None
            bucket = self._data.get(key)
            if bucket is None:
                self._stats["cache_misses"] += 1
                return None
            for entry in bucket:
                if entry.id == snapshot_id:
                    self._stats["cache_hits"] += 1
                    return entry
            self._stats["cache_misses"] += 1
            return None

    # ------------------------------------------------------------------
    # Capacity + TTL cleanup
    # ------------------------------------------------------------------
    def _maybe_purge_capacity(self) -> None:
        if self._max_entries <= 0:
            return
        total = sum(len(b) for b in self._data.values())
        while total > self._max_entries and self._data:
            oldest_key, oldest_bucket = self._data.popitem(last=False)
            evicted = len(oldest_bucket)
            self._stats["cache_evictions_capacity"] += evicted
            for e in oldest_bucket:
                self._id_index.pop(e.id, None)
            total -= evicted

    def cleanup(self, now: Optional[datetime] = None) -> int:
        cutoff = self._as_utc(now or datetime.now(timezone.utc)) - timedelta(seconds=self._ttl_seconds)
        evicted = 0
        with self._lock:
            for key in list(self._data.keys()):
                bucket = self._data[key]
                if not bucket:
                    del self._data[key]
                    continue
                # All entries share the same region; check the newest (bucket[0]).
                if bucket[0].observed_at is not None and bucket[0].observed_at < cutoff:
                    evicted += len(bucket)
                    self._stats["cache_evictions_ttl"] += len(bucket)
                    for e in bucket:
                        self._id_index.pop(e.id, None)
                    del self._data[key]
            self._ops_since_purge += 1
        return evicted

    # ------------------------------------------------------------------
    # Inspection + diagnostics
    # ------------------------------------------------------------------
    def size(self) -> int:
        with self._lock:
            return sum(len(b) for b in self._data.values())

    def region_count(self) -> int:
        with self._lock:
            return len(self._data)

    def public_stats(self) -> dict:
        with self._lock:
            total = self._stats["cache_hits"] + self._stats["cache_misses"]
            return {
                "size": self.size(),
                "regions": self.region_count(),
                "max_entries": self._max_entries,
                "ttl_seconds": self._ttl_seconds,
                "hits": self._stats["cache_hits"],
                "misses": self._stats["cache_misses"],
                "inserts": self._stats["cache_inserts"],
                "evictions_ttl": self._stats["cache_evictions_ttl"],
                "evictions_capacity": self._stats["cache_evictions_capacity"],
                "hit_rate": round(self._stats["cache_hits"] / total, 4) if total else 0.0,
            }

    def reset_stats(self) -> None:
        with self._lock:
            for k in list(self._stats.keys()):
                self._stats[k] = 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
