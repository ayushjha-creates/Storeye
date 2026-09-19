# M29 — Edge Pipeline Performance Report (measured-only)

Status: **code + tests complete; hardware phase pending a human at the store.**

This document reports the M29 change for the real-world AI reliability milestone
(M27). Every number below is a measurement taken on the development machine —
nothing is fabricated, extrapolated, or "expected". Items that could not be
measured honestly are listed explicitly as pending in the *Not yet measured*
section.

## What M29 changes

1. **Cascaded pipeline with a stability gate.** A local ByteTrack track must be
   seen on `stable_track_min_frames` consecutive frames before it becomes a
   candidate for Re-ID / zone events / journey association. This removes
   one-frame noise from becoming "a person" (the root cause of junk journeys).
   Default `1` keeps old behavior; runtimes can raise it globally or per camera.
2. **Layer-A hot person cache.** One store-scoped, in-memory
   `PersonStateManager` per edge runtime (LRU + TTL). Key = opaque
   `(store_id, global_person_id)` — never a face, crop, embedding, or raw frame.
   Embeddings live **in memory only**; nothing biometric is written to
   PostgreSQL (unchanged M19 constraint).
3. **Selective Re-ID.** On the hot path the pipeline reuses the cached global id
   with a cheap recency touch instead of re-encoding an embedding every frame
   (`reid_skips`). The expensive encode+associate runs only on a new track, on
   a refresh cadence (`REID_REFRESH_INTERVAL_SECONDS`), or when the cache
   disagreed.
4. **Minimal durable analytics + retention.** Person events stay persisted (M13/
   M14/M19 camera dashboards preserved) but with a 24 h retention purge
   (`PERSON_OBSERVATION_RETENTION_HOURS`) and journey analytics retention of
   30 days (`PERSON_ANALYTICS_RETENTION_DAYS`). A store can set
   `PERSON_OBSERVATION_PERSISTENCE=false` for pure cache-only mode (zero PERSON
   writes). CLI: `backend/scripts/purge_analytics.py`.
5. **AI FPS pacing.** `ai_target_fps` throttles only the AI stages (not
   capture); the bounded deque drops the **oldest** frame on overflow.
6. **Stage timings.** Per-stage latency (person, product, OCR, pipeline, write)
   is profiled (p50/p95/max) and exposed via the edge status API + Advanced
   Diagnostics UI.

## Measured on this machine

Setup: macOS dev box, PostgreSQL session absent (file source), single real
YOLO11n person model (`models/yolo/yolo11n.pt`), `data/tests/tracking/
test_people.mp4` (~180 frames, single pass to EOF), worker as released.

### Run 1 — uncapped (`ai_target_fps=0`)

| metric                 | measured          |
|------------------------|-------------------|
| elapsed                | 7.36 s            |
| frames captured        | 180 (EOF)         |
| frames processed       | 72                |
| frames dropped         | 104 (57.8%)       |
| capture fps            | 24.45 (file rate) |
| inference fps          | 9.78              |
| person stage p50 / p95 | 70.5 / 120.4 ms   |
| first-frame warm-up    | 2101 ms (YOLO load) |

### Run 2 — paced (`ai_target_fps=4`)

| metric                 | measured          |
|------------------------|-------------------|
| elapsed                | 7.36 s            |
| frames processed       | 20                |
| frames dropped         | 156 (86.7%)       |
| capture fps            | 24.47 (file rate) |
| inference fps          | 2.72              |
| person stage p50 / p95 | 97.1 / 2316.4 ms  |
| person cache hit rate  | n/a (Re-ID off)   |

Interpretation (honest):

- At ~70 ms/frame the person stage sustains ~10 inference fps on this Mac for
  this clip; the **capture rate is the file's native rate and is not a USB
  camera measurement**.
- Pacing cuts AI load ~72%, which is the intended trade-off for multi-camera
  deployments.
- The 2.3 s spike is the first-call YOLO weight load / warm-up in the person
  stage, not steady-state.
- **Re-ID latency is NOT measured here**: no embedding provider model is
  installed on this machine (`models/reid/` absent). The selective-skip
  accounting is covered by unit tests (`tests/test_m29_pipeline.py`), and
  real Re-ID timing requires hardware verification.

## Not yet measured (explicitly pending — human with hardware)

- One person / 30 s walk-through on a physical USB camera.
- Two people simultaneously (distinct journeys, never merged).
- Leave-and-return within the same-camera re-acquisition window (one journey).
- Cross-camera handoff with real Re-ID embeddings.
- Product detection and shelf fill on a live camera.
- Live mobile USB scanning and multi-camera (1/2/3/4+) concurrency.
- On-device AI FPS with the actual store machine/hardware.

These stay unclaimed until someone runs the scenario; the benchmark command is
provided so the numbers can be captured without extra tooling:

```
./.venv/bin/python -m scripts.benchmark_edge                # uncapped
./.venv/bin/python -m scripts.benchmark_edge --fps 4        # paced
./.venv/bin/python -m scripts.benchmark_edge --cam 0        # live USB
```

## Gates (all green)

- Backend: `TEST_DATABASE_URL="postgresql+psycopg2://storeye@localhost:5433/storeye_test" .venv/bin/pytest -q` → **508 passed** (487 baseline + 21 M29 tests).
- `alembic check` → no new upgrade operations (M29 is config/in-memory only).
- Frontend: `npx tsc -b`, `npx vitest run` (**153 passed**), `npm run build` green.
- No fabricated detections/counters; demo store remains deterministic and clearly labelled.
- No cloud, no face recognition, offline-first, local PostgreSQL stays authoritative.

## Files touched

- `backend/app/edge/person_cache.py` (new) — hot Layer-A store-scoped cache.
- `backend/app/edge/pipeline.py` — cascade, stability gate, selective Re-ID, stage timings.
- `backend/app/edge/workers.py` — AI pacing, StageProfiler, cache cleanup, status fields.
- `backend/app/edge/{observation_writer,runtime,config}.py` — persistence flag, runtime wiring, knobs.
- `backend/app/core/config.py`, `Storeye/.env.example` — M29 settings.
- `backend/app/services/journeys/journey_service.py` — `purge_analytics`.
- `backend/app/services/observations/observation_service.py` — `purge_person_observations`.
- `backend/scripts/purge_analytics.py` (new), `backend/scripts/benchmark_edge.py` (new).
- `backend/tests/test_person_cache.py`, `backend/tests/test_m29_pipeline.py` (new).
- Frontend: `DetectionStats.tsx`, `types.ts` (AI target FPS, Re-ID runs/skips, cache hit rate, stage latency row).