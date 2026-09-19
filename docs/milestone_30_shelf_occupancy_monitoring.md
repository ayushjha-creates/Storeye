# M30 — Periodic Shelf-Occupancy Monitoring

Status: **code + tests complete (backend 540 / frontend 157); hardware phase
pending a human at the store.**

This is M30 of the real-world AI reliability milestone (M27) workstream. Its job
is to give the operator a *periodic, honest* answer to "how full is each shelf
region right now" — decoupled from the live person-detection loop, written as
observations, and surfaced on the camera page. Every number is derived from real
camera frames by Product Detector box geometry; nothing is fabricated, guessed,
or extrapolated.

## What M30 changes

1. **Wall-clock snapshot cadence.** `shelf_snapshot_interval_seconds` (default
   30) drives a periodic sweep of the configured `shelf_regions` on a *real
   wall-clock gate*, independent of frame arrival rate. Product detection
   itself (`product_scan_interval_seconds`) is unchanged: `0` = every frame
   (legacy), `> 0` = seconds. `shelf_snapshot_interval_seconds = 0` disables
   snapshots for that camera.
2. **Occupancy classification + occlusion gate.** For each configured region,
   Product Detector boxes inside the region count toward `fill_percentage` and a
   4-state status: EMPTY (<10%) · LOW (10–<35%) · MEDIUM (35–<70%) · FULL (≥70%).
   If a tracked person box overlaps the region (`SKELETON/Person` bbox
   IoU ≥ `shelf_occlusion_overlap_fraction`, default 0.15) the snapshot is
   marked `occluded` — **never treated as real fill**, never counted as EMPTY,
   and retried on the next scan. Occlusion exists so a shopper standing in front
   of the shelf cannot masquerade as "the shelf is empty".
3. **Snapshots are OBSERVATIONS.** Each sweep writes a `shelf_snapshots` row
   (status, fill %, product count, confidence, store/camera/shelf scoping) plus
   JPEG crops on disk under `SHELF_SNAPSHOT_DIR` (`shelf_snapshots/` inside
   `EDGERETAIL_DATA_DIR`). Nothing here mutates inventory, batches, bills,
   planograms, or `shelves`. Paths in DB are **root-relative**; the image
   endpoint validates the resolved path stays under the snapshot root
   (path-traversal guard). Retention: `SHELF_SNAPSHOT_RETENTION_DAYS=7`
   (`purge_older_than` sweep deletes old rows + their files).
4. **Layer-A hot mirror (user decision: keep table, also mirror in cache).**
   PostgreSQL stays the authoritative store. On every successful write the
   worker pushes the row into a store-scoped in-memory
   `ShelfSnapshotCache` (LRU + TTL, one instance per edge runtime, same M29
   `PersonStateManager` pattern). The summary/history/trend/single APIs are
   **cache-first** and fall back to SQL on a miss. Image paths are **never**
   mirrored — the image endpoint always reads the durable row/disk.
5. **Camera-page monitor card.** `ShelfMonitor.tsx` under the live stream shows
   each configured region's fill bar + status badge, occluded warning, product
   count, and last-scan time, and refreshes with the page's live poll cycle.
   Honest empty state: "No shelf snapshots yet" until a running camera with
   product detection + shelf regions actually writes one.

## Configuration

| setting                                    | default | meaning                                             |
|--------------------------------------------|---------|-----------------------------------------------------|
| `shelf_snapshot_interval_seconds`          | 30      | wall-clock cadence (0 = disabled)                   |
| `shelf_occlusion_overlap_fraction`         | 0.15    | person-box overlap that flips a snapshot to occluded|
| `SHELF_SNAPSHOT_RETENTION_DAYS`            | 7       | durable rows + JPEG retention                       |
| `SHELF_SNAPSHOT_DIR`                       | `shelf_snapshots` | root-relative JPEG dir under data dir |
| `SHELF_SNAPSHOT_CACHE_TTL_SECONDS`         | 86400   | hot-mirror entry lifetime                           |
| `SHELF_SNAPSHOT_CACHE_MAX_ENTRIES`         | 4096    | hot-mirror capacity (LRU eviction)                  |
| `SHELF_SNAPSHOT_CACHE_PER_REGION_HISTORY`  | 24      | snapshots kept per `(store,camera,shelf)` for sparkline |

## API

- `GET /api/shelf-snapshots/summary?store_id=&camera_id=` — latest snapshot PER
  region (monitor-card payload), plus `status` counts and `last_scan_at`.
- `GET /api/shelf-snapshots/history?store_id=&camera_id=&shelf_code=&limit=` —
  one region's history (sparkline/trend data).
- `GET /api/shelf-snapshots/trend?store_id=&camera_id=&limit=` — last N per region.
- `GET /api/shelf-snapshots/{id}` — one row (404 for other-store rows).
- `GET /api/shelf-snapshots/{id}/image?prefer=crop|full` — streams the on-disk
  JPEG (ever-reads-the-DB; 404 if the file is gone). STAFF+ read role.
- Edge status adds `shelf_snapshots_written`, `last_shelf_scan_at`,
  `shelf_snapshot_cache` (canonical `public_stats` keys) on the camera status.

## Tests (backend +44 → 540)

- `tests/test_shelf_snapshots.py` (16): cadence model (0 = per-frame / disabled
  semantics), deterministic occupancy geometry + 4-state + occlusion gate, service
  persistence + root-relative paths + path-traversal guard + retention,
  API summary/history/single/image + 403/404 authz, cache-first summary (with
  store-scoped runtime; DB has zero rows when cache serves).
- `tests/test_shelf_snapshot_cache.py` (11): put/latest/history/by-id, store
  scoping, capacity LRU eviction, TTL cleanup, trend ordering, has_image
  mirroring, runtime wiring + status stats, cache works with zero DB wiring,
  canonical `public_stats()` keys.
- `tests/test_edge_ai.py`: worker mirror test (SHELF_SNAPSHOT event → service
  write → row mirrored into the runtime cache; status size reflects it).
- `tests/test_migrations.py` / `tests/test_startup_and_system.py`: new head
  `d5e8b0c2e4f6`, `shelf_snapshots` in table set.
- Frontend: `ShelfMonitor.test.tsx` (4): fill badges, empty state, occluded
  warning (no misleading fill bar), API error state.

## Gates (all green)

- Backend: `TEST_DATABASE_URL="postgresql+psycopg2://storeye@localhost:5433/storeye_test" .venv/bin/pytest -q` → **540 passed** (535 prior-state + M30 tests; the two stale migration-head assertions were updated to the new head).
- `alembic check` → clean (single `d5e8b0c2e4f6` migration; cache additions are in-memory only).
- Frontend: `npx tsc -b`, `npx vitest run` (**157 passed**), `npm run build` green.
- No fabricated fill/occlusion numbers; occluded regions never shown as empty.
- No cloud, no face recognition, offline-first, local PostgreSQL stays authoritative.

## Not yet measured (explicitly pending — human with hardware)

- Live-camera shelf-fill accuracy vs a physically staged (half-full / almost-empty)
  shelf, on an actual product SKU set.
- The occlusion gate against a real shopper standing in front of the shelf.
- Cross-product-class confusion on the 55-class shelf model (documented in
  `docs/model_capabilities.md`).
- Snapshot write latency + JPEG retention sweep on the store machine.

## Files touched

- `backend/app/models/shelf_snapshot.py` (new), `alembic/versions/d5e8b0c2e4f6_add_shelf_snapshots_table.py` (new).
- `backend/app/services/shelf_snapshot/shelf_snapshot_service.py` (new) — persist rows + JPEGs, retention, path guard.
- `backend/app/edge/shelf_snapshot_cache.py` (new) — Layer-A hot mirror.
- `backend/app/edge/{pipeline,config,workers,runtime}.py` — snapshot cadence + occlusion geometry; worker wiring; runtime cache manager; status fields.
- `backend/app/api/{edge_schemas.py, routers/shelf_snapshots.py}` — status fields + cache-first API.
- `backend/app/core/config.py` — M30 + cache settings.
- Frontend: `components/camera/ShelfMonitor.tsx` (new), `lib/api/shelfSnapshots.ts` (new), `lib/api/types.ts` (M30 types + edge-status fields), `pages/CameraDetail.tsx` (monitor card + live refresh key).