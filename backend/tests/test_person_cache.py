"""M29 — PersonStateManager unit tests (pure in-memory, no DB, no models).

Covers the Layer-A hot cache contract:
  * resolve_track / get hit-miss accounting + LRU recency
  * one global identity per (camera, track) — a re-seen track reuses its entry
  * TTL eviction via cleanup()
  * capacity LRU eviction
  * store isolation (same track id on another store never hits)
  * zone bookkeeping (enter stamps, zone-change restamps)
  * Re-ID accounting counters (invocation vs skip)
  * lifecycle transitions (mark_missing / close)
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

from app.edge.person_cache import (
    PersonState,
    PersonStateManager,
    STATE_ACTIVE,
    STATE_TEMPORARILY_MISSING,
    STATE_CLOSED,
)

pytestmark = [pytest.mark.no_db]


def _t(seconds: float) -> datetime:
    return datetime(2026, 9, 18, 9, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=seconds)


def test_insert_and_resolve_hit_after_miss():
    cache = PersonStateManager()
    assert cache.resolve_track("s1", "c1", 1) is None  # miss
    state = cache.upsert(
        store_id="s1", global_person_id="g1", camera_id="c1",
        track_id=1, timestamp=_t(0),
    )
    assert state.global_person_id == "g1"
    hit = cache.resolve_track("s1", "c1", 1)
    assert hit is not None and hit.global_person_id == "g1"
    stats = cache.stats()
    assert stats["cache_misses"] >= 1
    assert stats["cache_hits"] >= 1
    assert stats["cache_inserts"] == 1


def test_same_track_updates_single_state_no_duplicate():
    cache = PersonStateManager()
    cache.upsert(store_id="s1", global_person_id="g1", camera_id="c1", track_id=7, timestamp=_t(1))
    cache.upsert(store_id="s1", global_person_id="g1", camera_id="c1", track_id=7, timestamp=_t(2))
    cache.upsert(store_id="s1", global_person_id="g1", camera_id="c1", track_id=7, timestamp=_t(3))
    assert cache.size() == 1
    entries = cache.snapshot()
    assert entries[0]["total_detections"] == 3
    assert entries[0]["consecutive_detections"] == 3
    assert cache.stats()["existing_identity_reused"] >= 2


def test_ttl_eviction_after_cleanup():
    cache = PersonStateManager(ttl_seconds=60.0)
    cache.upsert(store_id="s1", global_person_id="g1", camera_id="c1", track_id=1, timestamp=_t(0))
    # Still fresh inside the TTL window.
    assert cache.cleanup(now=_t(30)) == 0
    assert cache.size() == 1
    # Idle past the TTL -> evicted.
    assert cache.cleanup(now=_t(120)) == 1
    assert cache.size() == 0
    assert cache.resolve_track("s1", "c1", 1) is None
    assert cache.stats()["cache_evictions_ttl"] == 1


def test_capacity_lru_eviction():
    cache = PersonStateManager(max_entries=3)
    for i in range(1, 5):
        cache.upsert(store_id="s1", global_person_id=f"g{i}", camera_id="c1", track_id=i, timestamp=_t(i))
    assert cache.size() == 3
    # g1 was the least-recently used -> evicted; newest three remain.
    assert cache.resolve_track("s1", "c1", 1) is None
    assert cache.resolve_track("s1", "c1", 4) is not None
    assert cache.stats()["cache_evictions_capacity"] == 1


def test_store_isolation_same_track_id_never_crosses_stores():
    cache = PersonStateManager()
    cache.upsert(store_id="s1", global_person_id="g1", camera_id="c1", track_id=3, timestamp=_t(0))
    # Same camera + track id but a DIFFERENT store -> miss, never a merge.
    assert cache.resolve_track("s2", "c1", 3) is None
    cache.upsert(store_id="s2", global_person_id="g2", camera_id="c1", track_id=3, timestamp=_t(1))
    assert cache.size() == 2
    assert cache.resolve_track("s1", "c1", 3).global_person_id == "g1"
    assert cache.resolve_track("s2", "c1", 3).global_person_id == "g2"


def test_zone_bookkeeping_stamps_entries_and_restamps_on_change():
    cache = PersonStateManager()
    cache.upsert(store_id="s1", global_person_id="g1", camera_id="c1", track_id=1, timestamp=_t(0), zone_id="a")
    entry = cache.resolve_track("s1", "c1", 1)
    assert entry.current_zone_id == "a"
    assert entry.current_zone_entered_at == _t(0)
    # Same zone -> no re-stamp.
    cache.upsert(store_id="s1", global_person_id="g1", camera_id="c1", track_id=1, timestamp=_t(1), zone_id="a")
    entry = cache.resolve_track("s1", "c1", 1)
    assert entry.current_zone_id == "a"
    assert entry.current_zone_entered_at == _t(0)
    # New zone -> restamp + remember the previous zone.
    cache.upsert(store_id="s1", global_person_id="g1", camera_id="c1", track_id=1, timestamp=_t(5), zone_id="b")
    entry = cache.resolve_track("s1", "c1", 1)
    assert entry.current_zone_id == "b"
    assert entry.current_zone_entered_at == _t(5)
    assert entry.last_zone_id == "a"


def test_reid_counters():
    cache = PersonStateManager()
    cache.count_reid_invocation()
    cache.count_reid_skip()
    cache.count_reid_invocation()
    stats = cache.stats()
    assert stats["reid_invocations"] == 2
    assert stats["reid_skipped"] == 1
    cache.reset_stats()
    assert cache.stats()["reid_invocations"] == 0


def test_new_identity_vs_reuse_accounting():
    cache = PersonStateManager()
    cache.upsert(store_id="s1", global_person_id="g1", camera_id="c1", track_id=1, timestamp=_t(0), reid_used=True)
    cache.upsert(store_id="s1", global_person_id="g1", camera_id="c1", track_id=1, timestamp=_t(1), reid_used=False)
    stats = cache.stats()
    assert stats["new_global_identity"] == 1
    assert stats["existing_identity_reused"] == 1


def test_missing_and_close_transitions():
    cache = PersonStateManager(missing_grace_seconds=5.0)
    cache.upsert(store_id="s1", global_person_id="g1", camera_id="c1", track_id=1, timestamp=_t(0))
    assert cache.resolve_track("s1", "c1", 1).state == STATE_ACTIVE
    # Within the grace window: still active.
    cache.mark_missing("s1", "g1", _t(2))
    assert cache.resolve_track("s1", "c1", 1).state == STATE_ACTIVE
    # Past grace: temporarily missing.
    cache.mark_missing("s1", "g1", _t(8))
    assert cache.resolve_track("s1", "c1", 1).state == STATE_TEMPORARILY_MISSING
    # Return re-activates (upsert restamps state=active).
    cache.upsert(store_id="s1", global_person_id="g1", camera_id="c1", track_id=1, timestamp=_t(9))
    assert cache.resolve_track("s1", "c1", 1).state == STATE_ACTIVE
    cache.close("s1", "g1", _t(10))
    assert cache.resolve_track("s1", "c1", 1).state == STATE_CLOSED


def test_concurrent_thread_safety_smoke():
    cache = PersonStateManager(max_entries=64)

    def worker(worker_id: int):
        for i in range(200):
            cache.upsert(
                store_id="s1",
                global_person_id=f"w{worker_id}",
                camera_id="c1",
                track_id=worker_id,
                timestamp=_t(i),
            )
            cache.resolve_track("s1", "c1", worker_id)

    threads = [threading.Thread(target=worker, args=(w,)) for w in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert cache.size() == 8
    assert cache.stats()["cache_hits"] > 0