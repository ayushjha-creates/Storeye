# Milestone 14 — Production Camera + AI Intelligence Dashboard

**Date:** 2026-09-07
**Status:** ✅ Implemented and verified

---

## Summary

Storeye's dashboard now surfaces the M13 Edge AI runtime as a usable retail-intelligence
experience — all from **real** observations. A camera overview grid with live previews,
a per-camera detail view with an explicit RAW / AI-annotated stream toggle, detection
statistics, AI runtime performance, and a server-paginated observation history replace
earlier demo placeholders. PostgreSQL remains the single business database, FastAPI is
the only API boundary, and the whole experience is edge-first: internet is never required
for cameras, AI or data.

## What was delivered

| Area | Detail |
|------|--------|
| Observation queries | `observation_service.query_observations` — SQL-side filters (`store_id`, `camera_id`, `product_id`, `observation_type`, `confidence_min`, `from`/`to`) + `limit`/`offset` with a true `total` count; `observation_summary` — last-N-hour activity (1–168 h) with hourly buckets, `by_type`, `distinct_tracks`, `avg_confidence`, `last_observed_at` |
| API | `GET /api/observations` — now paged + filtered; **new** `GET /api/observations/summary` (registered before `/{obs_id}`); invalid `observation_type` → 422 via global error mapping |
| Camera schema | `config` validated (`kind` ∈ usb/file/rtsp, `source`/`streamUrl` strings, pipeline flags booleans) and `camera_type` validated on create/update; config values never reach a shell (Edge uses `cv2.VideoCapture` only) |
| Camera grid | `Cameras.tsx` — health derivation (LIVE/CONNECTING/ERROR/READY/STOPPED), live MJPEG thumbs with graceful placeholder on failure, per-camera 24 h people/products, 30 s silent polling, per-camera isolated error handling, `edge.error` surfaced |
| Camera detail | `CameraDetail.tsx` — explicit **RAW / AI ANNOTATED** stream toggle (defaults; never overrides a user toggle), summary fetch, `DetectionStats` panel |
| Detection stats | `components/camera/DetectionStats.tsx` — totals by type, avg confidence, tracked people, last seen, CSS activity bars (zero-filled), AI runtime performance (FPS/frames/drop rate/observations written/uptime/pipeline badges), explicit "Not available" and "AI runtime status not available" instead of invented numbers |
| Observation history | `Observations.tsx` — server-side pagination (`PAGE_SIZE=50`), camera/type/min-confidence/date filters, 24 h summary header cards, Reset, Prev/Next, empty states |
| Node status | `EdgeNodeStatus.tsx` — real AI Runtime state (RUNNING/STOPPED/CHECKING/UNKNOWN), active-camera counters, models loaded, green **Edge Mode** strip when internet is down yet the node runs |
| Tests | +15 frontend tests (green under EDGE-mode contexts; `Cameras`/`Observations` stayed context-free), +backend suite for pagination/summary/config validation |

## Verification (honest numbers)

### Backend
- Full suite `pytest -m "not no_real_ai"`: **162 passed** (4 warnings).
- New `test_api.py` coverage: pagination + true `total`, summary invariants
  (bucket-sum == total, `by_type`, `distinct_tracks`, zero-camera case), and the
  camera `config`/`camera_type` 422 suite.
- `ObservationService.ValidationError` → HTTP 422 globally via `app/api/errors.py`.

### Frontend
- **58 tests pass** (`npx vitest run`, 15 files), `npx tsc -b` clean, **`npm run build` passes**.

### Live integration (dev storeye DB, temp API on :8099, real YOLO11n + ByteTrack)
| Check | Result |
|-------|--------|
| Camera create with validated `config` | 201 |
| Fresh-camera summary/list | total 0 (no fabricated history) |
| `/api/edge/cameras/{id}/start` | 200 |
| Real detections persisted | 10 PERSON observations, 2 distinct tracks, ~9.8 fps (matches the documented ~6–11 fps CPU bound) |
| Summary aggregation | total=10, `by_type.PERSON=10`, bucket-sum == total, 25 hourly buckets |
| Pagination + filter | `limit=5` → 5 items / total 10; `PERSON&confidence_min=0.9` narrows to 0 |
| Streams | annotated + raw MJPEG both served as `multipart/x-mixed-replace`, `?fps=` honored |
| Clean stop | 200, `running=false` |

The verified dev DB now contains one demo file camera ("M14 Integration Cam",
source `data/tests/tracking/test_people.mp4`) with its real observations, so the
dashboard shows genuine data on open. Demo/test-sample data is clearly that; no
fake production numbers are ever substituted for unavailable data.

## Edge-first / offline guarantees
- No internet required for cameras, AI inference or PostgreSQL (verified live with
  person/shelf pipelines locally weighted; no HTTP/socket/urlopen in `app/edge`).
- **Todo (future offline-deployment milestone):** PaddleOCR, when first enabled on a
  fresh machine, downloads its models once and caches them in `~/.paddleocr`. A
  never-initialized machine without internet cannot bootstrap OCR. An offline
  deployment/install packaging milestone must vendor/predict these models.

## Safety & scope boundaries (unchanged)
- AI observations are **informational only** — the edge writer uses `ObservationService`
  and never mutates inventory, stock movements, batches, bills or sales.
- PostgreSQL (storeye) remains the single business DB — no MongoDB/Firebase/Redis, and
  no business data lives in localStorage as a PG substitute.
- No auth implementation (the existing Login note remains accurate).

## Root-cause fixes landed this milestone
- Duplicate LIVE badge text on camera tiles caused ambiguous test matches → removed the
  redundant chip (Badge already shows LIVE).
- Summary router colliding with `/{obs_id}` → registered before it.

## Not built (explicitly out of scope)
Supabase / cloud sync / AI auto-billing / AI bills / auto-reconciliation / face
recognition / biometrics / distributed infra / second business database / offline
install packaging (see the PaddleOCR todo above).

## Next
M15 (per roadmap).