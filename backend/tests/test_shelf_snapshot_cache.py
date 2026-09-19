"""M30 — ShelfSnapshotCache (Layer-A hot mirror) tests.

The shelf-snapshot cache mirrors authoritative PostgreSQL rows into a
thread-safe bounded LRU+TTL in-memory store so the monitor card + history read
from memory. PostgreSQL remains authoritative: consumers fall back to SQL on a
miss. Tests here cover the cache itself plus the runtime wiring (mirroring
exactly what the worker pushes).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.edge.runtime import EdgeRuntime
from app.edge.shelf_snapshot_cache import ShelfSnapshotCache
from app.models import ShelfSnapshot

pytestmark = pytest.mark.no_db


def _row(
    *,
    store_id: str = "s1",
    camera_id: str = "c1",
    shelf_code: str = "S1",
    observed_at: datetime | None = None,
    status: str = "MEDIUM",
    fill: float = 45.0,
    occluded: bool = False,
    with_files: bool = True,
) -> ShelfSnapshot:
    return ShelfSnapshot(
        id=uuid4(),
        store_id=store_id,
        camera_id=camera_id,
        shelf_code=shelf_code,
        shelf_label=None,
        region_bbox=[0.0, 0.0, 0.5, 1.0],
        snapshot_path="c1/20260918/000000000000_S1_full.jpg" if with_files else None,
        crop_path="c1/20260918/000000000000_S1_crop.jpg" if with_files else None,
        fill_percentage=fill,
        status=status,
        product_count=3,
        occluded=occluded,
        occlusion_note="Person blocking" if occluded else None,
        confidence=0.9,
        observed_at=observed_at or datetime.now(timezone.utc),
    )


def test_put_and_latest_and_history():
    cache = ShelfSnapshotCache(store_id="s1")
    t0 = datetime(2026, 9, 18, 10, 0, 0, tzinfo=timezone.utc)
    first = _row(observed_at=t0, status="LOW", fill=20.0)
    second = _row(observed_at=t0 + timedelta(seconds=30), status="MEDIUM", fill=45.0)
    cache.put(first)
    cache.put(second)

    latest = cache.latest("s1", "c1")
    assert set(latest) == {"S1"}
    assert latest["S1"].id == str(second.id)
    assert latest["S1"].status == "MEDIUM"

    history = cache.history("s1", "c1", "S1", limit=10)
    assert [e.id for e in history] == [str(second.id), str(first.id)]  # newest first

    single = cache.get_by_id(str(first.id))
    assert single.id == str(first.id)


def test_put_is_store_scoped():
    cache = ShelfSnapshotCache(store_id="s1")
    cache.put(_row(store_id="s1"))
    assert cache.latest("s1", "c1") != {}
    assert cache.latest("other", "c1") == {}


def test_capacity_evicts_oldest_region():
    cache = ShelfSnapshotCache(store_id="s1", max_entries=2, per_region_history=2)
    a = _row(shelf_code="A")
    b = _row(shelf_code="B")
    c = _row(shelf_code="C")
    cache.put(a)
    cache.put(b)
    cache.put(c)
    stats = cache.public_stats()
    assert stats["evictions_capacity"] >= 1
    # Oldest region (A) evicted; remaining are B and C.
    assert set(cache.latest("s1", "c1").keys()) == {"B", "C"}


def test_ttl_cleanup_evicts_stale():
    cache = ShelfSnapshotCache(store_id="s1", ttl_seconds=10.0)
    cache.put(_row(observed_at=datetime.now(timezone.utc) - timedelta(seconds=60)))
    evicted = cache.cleanup(now=datetime.now(timezone.utc))
    assert evicted == 1
    assert cache.latest("s1", "c1") == {}
    stats = cache.public_stats()
    assert stats["evictions_ttl"] == 1


def test_trend_flattens_regions_newest_first():
    cache = ShelfSnapshotCache(store_id="s1")
    base = datetime(2026, 9, 18, 10, 0, 0, tzinfo=timezone.utc)
    cache.put(_row(shelf_code="A", observed_at=base))
    cache.put(_row(shelf_code="B", observed_at=base + timedelta(seconds=10)))
    cache.put(_row(shelf_code="A", observed_at=base + timedelta(seconds=20)))
    trend = cache.trend("s1", "c1", limit=10)
    codes = [(e.shelf_code, e.observed_at) for e in trend]
    assert codes[0][0] == "A" and codes[0][1] > codes[1][1]
    assert len(trend) == 3


def test_row_to_read_dict_marks_has_image():
    cache = ShelfSnapshotCache(store_id="s1")
    cache.put(_row(with_files=True))
    cache.put(_row(shelf_code="S2", with_files=False))
    latest = cache.latest("s1", "c1")
    assert latest["S1"].has_image is True
    assert latest["S2"].has_image is False
    d = latest["S1"].to_read_dict()
    assert d["has_image"] is True and d["snapshot_path"] is None


# ---------------------------------------------------------------------------
# Runtime wiring: worker mirrors rows into the runtime cache
# ---------------------------------------------------------------------------
def _make_console_runtime():
    runtime = EdgeRuntime()
    runtime.set_store("s1")
    return runtime


def test_runtime_wires_shared_shelf_cache():
    runtime = _make_console_runtime()
    cache = runtime.get_shelf_snapshot_cache()
    assert cache is not None
    assert cache.public_stats()["size"] == 0
    # Same instance every call (created ONCE, like the person cache).
    assert runtime.get_shelf_snapshot_cache() is cache


def test_runtime_status_includes_shelf_cache_after_insert():
    runtime = _make_console_runtime()
    cache = runtime.get_shelf_snapshot_cache()
    cache.put(_row(store_id="s1"))
    status = runtime.status()
    assert status["shelf_snapshot_cache"]["size"] == 1


def test_runtime_cache_respects_store_binding():
    runtime = _make_console_runtime()
    runtime.set_store("s1")
    cache = runtime.get_shelf_snapshot_cache()
    # A put for a different store is refused (store-scoped singleton).
    cache.put(_row(store_id="outside"))
    assert cache.latest("s1", "c1") == {}


def test_cache_survives_without_db_engine():
    """The cache never touches SQL — usable with zero DB wiring."""
    cache = ShelfSnapshotCache(store_id="s1")
    cache.put(_row())
    assert cache.latest("s1", "c1")["S1"].fill_percentage == 45.0


def test_public_stats_stable_keys():
    cache = ShelfSnapshotCache(store_id="s1")
    stats = cache.public_stats()
    for key in (
        "size",
        "regions",
        "max_entries",
        "ttl_seconds",
        "hits",
        "misses",
        "inserts",
        "evictions_ttl",
        "evictions_capacity",
        "hit_rate",
    ):
        assert key in stats