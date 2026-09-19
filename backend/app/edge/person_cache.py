"""M29 — Hot person-state cache (Layer A: real-time high-frequency state).

ARCHITECTURE (M29)
------------------
Storeye keeps TWO data layers:

  * Layer A — HOT CACHE (this module). High-frequency person state that the
    edge AI runtime needs while a camera is live: which anonymous global id a
    local (camera, track) is currently assigned to, which zone they are in,
    when they entered it, detection continuity counters, and the ephemeral
    memory-only appearance embedding. Nothing here is ever written to
    PostgreSQL.

  * Layer B — DURABLE ANALYTICS (PostgreSQL, see JourneyService). Only the
    minimal session/zone aggregates needed for business analytics (dwell time,
    zone time, session summaries) and their retention is governed by
    PERSON_ANALYTICS_RETENTION_DAYS.

The cache is owned by the edge runtime (one instance per store), lives for the
whole runtime session, and is created exactly once at runtime startup — never
per frame, per request, or per observation.

PRIVACY
-------
Keys are opaque store-scoped (store_id, global_person_id) pairs — the cache key
for a user-hash example would be ``store_123:person_8f92a``. It is NEVER shown
to normal users. The cache stores no names, no faces, no phone numbers, no
email identity, and no raw frames. Appearance embeddings (anonymous, memory
only) may be held here for the ~TTL lifetime of the runtime session, exactly as
the Re-ID manager already does.

RETENTION
---------
  * HOT: entries idle beyond ``ttl_seconds`` (default PERSON_CACHE_TTL_SECONDS,
    86400 = 24h) are evicted by ``cleanup()``.
  * DURABLE: retention of POSTGRESQL analytics is handled separately by
    JourneyService.purge_analytics (PERSON_ANALYTICS_RETENTION_DAYS).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from ..services.journeys.reid.models import Confidence, PersonEmbedding

logger = logging.getLogger("storeye.edge.person_cache")

# Person lifecycle states visible to advanced diagnostics only.
STATE_ACTIVE = "active"                        # currently visible (cached)
STATE_TEMPORARILY_MISSING = "temporarily_missing"  # last seen <= grace window
STATE_CLOSED = "closed"                        # gone beyond grace / TTL-evicted

CacheKey = Tuple[str, str]  # (store_id, global_person_id)
TrackKey = Tuple[str, str, int]  # (store_id, camera_id, track_id) — store-scoped


class PersonState:
    """One anonymous person's live state in the hot cache."""

    __slots__ = (
        "store_id",
        "global_person_id",
        "state",
        "current_camera_id",
        "current_track_id",
        "current_zone_id",
        "first_seen_at",
        "last_seen_at",
        "last_camera_id",
        "last_zone_id",
        "current_zone_entered_at",
        "appearance_embedding",
        "confidence",
        "consecutive_detections",
        "total_detections",
        "reid_match_count",
    )

    def __init__(
        self,
        *,
        store_id: str,
        global_person_id: str,
        camera_id: str,
        track_id: int,
        timestamp: datetime,
        zone_id: Optional[str] = None,
        embedding: Optional[PersonEmbedding] = None,
        confidence: str = Confidence.UNKNOWN.value,
    ) -> None:
        self.store_id = store_id
        self.global_person_id = global_person_id
        self.state = STATE_ACTIVE
        self.current_camera_id = camera_id
        self.current_track_id = track_id
        self.current_zone_id = zone_id
        self.first_seen_at = timestamp
        self.last_seen_at = timestamp
        self.last_camera_id = camera_id
        self.last_zone_id = zone_id
        self.current_zone_entered_at = timestamp if zone_id else None
        self.appearance_embedding = embedding
        self.confidence = confidence
        self.consecutive_detections = 1
        self.total_detections = 1
        self.reid_match_count = 0

    def to_snapshot(self) -> dict:
        """Diagnostics-only projection (never exposed to normal APIs)."""
        return {
            "store_id": self.store_id,
            "global_person_id": self.global_person_id,
            "state": self.state,
            "current_camera_id": self.current_camera_id,
            "current_track_id": self.current_track_id,
            "current_zone_id": self.current_zone_id,
            "first_seen_at": self.first_seen_at.isoformat(),
            "last_seen_at": self.last_seen_at.isoformat(),
            "last_camera_id": self.last_camera_id,
            "last_zone_id": self.last_zone_id,
            "current_zone_entered_at": (
                self.current_zone_entered_at.isoformat()
                if self.current_zone_entered_at
                else None
            ),
            "confidence": self.confidence,
            "consecutive_detections": self.consecutive_detections,
            "total_detections": self.total_detections,
            "has_embedding": self.appearance_embedding is not None,
        }


class PersonStateManager:
    """Thread-safe store-scoped LRU+TTL cache of live anonymous person state.

    Created once per edge runtime (never per frame). ``resolve_track`` is the
    hot-path lookup the pipeline uses to reuse an identity instead of running
    expensive Re-ID again.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = 86400.0,
        max_entries: int = 2048,
        missing_grace_seconds: float = 15.0,
        store_id: Optional[str] = None,
    ) -> None:
        self._ttl_seconds = float(ttl_seconds)
        self._max_entries = int(max_entries)
        self._missing_grace_seconds = float(missing_grace_seconds)
        self.store_id = store_id
        self._entries: "OrderedDict[CacheKey, PersonState]" = OrderedDict()
        self._track_index: Dict[TrackKey, CacheKey] = {}
        self._lock = threading.RLock()
        # Counters (surfaced only in Advanced Diagnostics, never normal APIs).
        self._stats = {
            "cache_hits": 0,
            "cache_misses": 0,
            "cache_inserts": 0,
            "cache_evictions_ttl": 0,
            "cache_evictions_capacity": 0,
            "reid_invocations": 0,
            "reid_skipped": 0,
            "new_global_identity": 0,
            "existing_identity_reused": 0,
        }
        self._cleanup_runs: int = 0

    # ------------------------------------------------------------------
    # Hot-path track resolution
    # ------------------------------------------------------------------
    def resolve_track(
        self, store_id: str, camera_id: str, track_id: int
    ) -> Optional[PersonState]:
        """Return the cached person for a local (camera, track), counting a
        hit on success. This is the first thing the pipeline consults before
        deciding whether expensive Re-ID is needed."""
        with self._lock:
            key = self._track_index.get((store_id, camera_id, int(track_id)))
            if key is None or key not in self._entries:
                self._stats["cache_misses"] += 1
                return None
            entry = self._entries[key]
            if entry.store_id != store_id:
                self._stats["cache_misses"] += 1
                return None
            # LRU touch.
            self._entries.move_to_end(key)
            self._stats["cache_hits"] += 1
            return entry

    def get(self, store_id: str, global_person_id: str) -> Optional[PersonState]:
        with self._lock:
            entry = self._entries.get((store_id, global_person_id))
            if entry is not None:
                self._entries.move_to_end((store_id, global_person_id))
                self._stats["cache_hits"] += 1
            else:
                self._stats["cache_misses"] += 1
            return entry

    # ------------------------------------------------------------------
    # Insert / update
    # ------------------------------------------------------------------
    def upsert(
        self,
        *,
        store_id: str,
        global_person_id: str,
        camera_id: str,
        track_id: int,
        timestamp: datetime,
        zone_id: Optional[str] = None,
        embedding: Optional[PersonEmbedding] = None,
        confidence: str = Confidence.UNKNOWN.value,
        reid_used: bool = False,
    ) -> PersonState:
        """Create or refresh the cache entry for a global person.

        ``reid_used=True`` marks this sighting as the result of an expensive
        Re-ID decision (new identity or fresh association), incrementing
        ``new_global_identity`` / ``existing_identity_reused`` accordingly and
        allowing the pipeline to prove the cascade is reducing work.
        """
        with self._lock:
            now = self._as_utc(timestamp)
            key = (store_id, global_person_id)
            entry = self._entries.get(key)
            created = entry is None
            if created:
                entry = PersonState(
                    store_id=store_id,
                    global_person_id=global_person_id,
                    camera_id=camera_id,
                    track_id=track_id,
                    timestamp=now,
                    zone_id=zone_id,
                    embedding=embedding,
                    confidence=confidence,
                )
                self._entries[key] = entry
                self._stats["cache_inserts"] += 1
                if reid_used:
                    self._stats["new_global_identity"] += 1
            else:
                self._entries.move_to_end(key)
                entry.consecutive_detections += 1
                entry.total_detections += 1
                # Reuse existing identity when the global id is unchanged.
                if entry.global_person_id == global_person_id:
                    self._stats["existing_identity_reused"] += 1

            if created or entry.global_person_id != global_person_id:
                self._swap_id(entry, global_person_id)

            entry.state = STATE_ACTIVE
            entry.last_seen_at = now
            entry.last_camera_id = camera_id
            entry.current_camera_id = camera_id
            entry.current_track_id = int(track_id)
            entry.confidence = confidence or entry.confidence
            if embedding is not None and embedding.values:
                entry.appearance_embedding = embedding
            if reid_used:
                entry.reid_match_count += 1

            # Zone bookkeeping lives here: entering a NEW zone (or a
            # different one) stamps current_zone_entered_at.
            if zone_id is not None and zone_id != entry.current_zone_id:
                entry.last_zone_id = entry.current_zone_id
                entry.current_zone_id = zone_id
                entry.current_zone_entered_at = now

            self._track_index[(store_id, camera_id, int(track_id))] = key
            if created:
                self._trim_capacity()
            return entry

    def _swap_id(self, entry: PersonState, global_person_id: str) -> None:
        old = entry.global_person_id
        entry.global_person_id = global_person_id
        # Re-key the OrderedDict when the global id changed (re-association).
        store_id = entry.store_id
        if (store_id, old) in self._entries:
            self._entries.pop((store_id, old))
        self._entries[(store_id, global_person_id)] = entry
        # Re-point track index entries that referenced the old id.
        for tk, ck in list(self._track_index.items()):
            if tk[0] == store_id and ck == (store_id, old):
                self._track_index[tk] = (store_id, global_person_id)

    # ------------------------------------------------------------------
    # Lifecycle transitions
    # ------------------------------------------------------------------
    def mark_missing(self, store_id: str, global_person_id: str, now: datetime) -> None:
        """Flip an active entry to TEMPORARILY_MISSING when it stops appearing
        (the Re-ID manager's grace window). A return within the window reuses
        the cached identity without a new journey."""
        with self._lock:
            entry = self._entries.get((store_id, global_person_id))
            if entry is None:
                return
            now = self._as_utc(now)
            if entry.state == STATE_ACTIVE and (now - entry.last_seen_at).total_seconds() >= self._missing_grace_seconds:
                entry.state = STATE_TEMPORARILY_MISSING

    def close(self, store_id: str, global_person_id: str, now: datetime) -> None:
        with self._lock:
            entry = self._entries.get((store_id, global_person_id))
            if entry is None:
                return
            entry.state = STATE_CLOSED
            entry.last_seen_at = self._as_utc(now)

    # ------------------------------------------------------------------
    # Capacity + cleanup
    # ------------------------------------------------------------------
    def _trim_capacity(self) -> None:
        with self._lock:
            if self._max_entries <= 0:
                return
            while len(self._entries) > self._max_entries:
                key, entry = self._entries.popitem(last=False)
                self._stats["cache_evictions_capacity"] += 1
                ts = list(self._track_index.items())
                for tk, ck in ts:
                    if ck == key:
                        del self._track_index[tk]
                logger.info(
                    "Person cache capacity eviction: %s (idle %ss)",
                    key[1],
                    max(0, (self._now() - entry.last_seen_at).total_seconds()),
                )

    def cleanup(self, now: Optional[datetime] = None) -> int:
        """Evict entries idle beyond the TTL. Call periodically (never per
        frame). Returns the number of evictions."""
        cutoff = self._as_utc(now or self._now()) - timedelta(seconds=self._ttl_seconds)
        evicted = 0
        with self._lock:
            for key, entry in list(self._entries.items()):
                if entry.last_seen_at < cutoff:
                    del self._entries[key]
                    self._stats["cache_evictions_ttl"] += 1
                    evicted += 1
            if evicted:
                remaining = set(self._entries.keys())
                self._track_index = {
                    tk: ck for tk, ck in self._track_index.items() if ck in remaining
                }
            self._cleanup_runs += 1
        if evicted:
            logger.info("Person cache cleanup evicted %d stale entr%s", evicted, "ies" if evicted != 1 else "y")
        return evicted

    # ------------------------------------------------------------------
    # Inspection + diagnostics
    # ------------------------------------------------------------------
    def active_count(self) -> int:
        with self._lock:
            return sum(1 for e in self._entries.values() if e.state == STATE_ACTIVE)

    def size(self) -> int:
        with self._lock:
            return len(self._entries)

    def snapshot(self) -> List[dict]:
        with self._lock:
            return [e.to_snapshot() for e in self._entries.values()]

    def stats(self) -> dict:
        with self._lock:
            out = dict(self._stats)
            out["cache_entries"] = len(self._entries)
            out["cleanup_runs"] = self._cleanup_runs
            total = out["cache_hits"] + out["cache_misses"]
            out["cache_hit_rate"] = round(out["cache_hits"] / total, 4) if total else 0.0
            return out

    def public_stats(self) -> dict:
        """Canonical M29 payload for the edge status API (stable key names so
        the frontend never needs to know internal counter names)."""
        with self._lock:
            total = self._stats["cache_hits"] + self._stats["cache_misses"]
            return {
                "size": len(self._entries),
                "max_entries": self._max_entries,
                "ttl_seconds": self._ttl_seconds,
                "hits": self._stats["cache_hits"],
                "misses": self._stats["cache_misses"],
                "inserts": self._stats["cache_inserts"],
                "evictions_ttl": self._stats["cache_evictions_ttl"],
                "evictions_capacity": self._stats["cache_evictions_capacity"],
                "reid_invocations": self._stats["reid_invocations"],
                "reid_skipped": self._stats["reid_skipped"],
                "new_global_identity": self._stats["new_global_identity"],
                "existing_identity_reused": self._stats["existing_identity_reused"],
                "hit_rate": round(self._stats["cache_hits"] / total, 4) if total else 0.0,
            }

    def reset_stats(self) -> None:
        with self._lock:
            for k in self._stats:
                self._stats[k] = 0
            self._cleanup_runs = 0

    # ------------------------------------------------------------------
    # Re-ID accounting (pipeline pushes these so the cache is the single
    # place Advanced Diagnostics reads them from).
    # ------------------------------------------------------------------
    def count_reid_invocation(self) -> None:
        """Record one expensive Re-ID embedding+association run."""
        with self._lock:
            self._stats["reid_invocations"] += 1

    def count_reid_skip(self) -> None:
        """Record one frame where Re-ID embedding inference was skipped."""
        with self._lock:
            self._stats["reid_skipped"] += 1

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)