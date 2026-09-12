# Milestone 13 — Edge AI Runtime + Live Camera Integration

**Date:** 2026-09-06
**Status:** ✅ Implemented and verified

---

## Summary

Storeye now runs a real, multi-camera, offline-first Edge AI runtime inside the
backend: YOLO11n person detection + ByteTrack tracking, shelf/product detection,
PaddleOCR + expiry parsing, PostgreSQL observation persistence, a FastAPI control +
MJPEG streaming API, and live React integration on the existing camera pages.

## What was delivered

| Area | Detail |
|------|--------|
| Runtime | `app/edge/runtime.py` — per-camera `CameraWorker`, start/stop/status/remove, EOF auto-stop, multi-camera isolation |
| Workers | `app/edge/workers.py` — capture/inference threads, bounded newest-frame-wins queue, file-source FPS pacing, throttled observation writer (session closed per batch — no connection leaks) |
| Camera sources | file / webcam / RTSP (`app/edge/camera.py` + `create_camera_source`) |
| Models | YOLO11n + ByteTrack (person), shelf/product detector, PaddleOCR + ExpiryParser — wrapped behind injectable interfaces with fakes for tests (`app/edge/models/`) |
| Persistence | `ObservationWriter` → existing `ObservationService`; per-kind throttle, valid-UUID guard, camera-FK fallback to `NULL`; never touches inventory/batches/bills/sales |
| API | `/api/edge/status`, `/api/edge/cameras`, `/api/edge/cameras/{id}`, `/start`, `/stop`, `/api/edge/stream/{id}` (MJPEG, ends when worker stops) |
| Frontend | `CameraDetail.tsx` (AI badge, Start/Stop, live stream, fps) and `Cameras.tsx` (LIVE pill, RUNNING badge, fps + observation stats), best-effort edge calls |
| Docs | `docs/edge-ai.md` (architecture, API, benchmarks, offline behaviour, limitations) |

## Verification (honest numbers)

### Backend tests
- Full suite (`pytest -m "not real_ai"`): **158 passed**
- Full suite including the marked real-model smoke (`-m real_ai`): **159 total**
- `tests/test_edge_ai.py` — fake-model unit tests (events, confidence gating, OCR
  cadence, runtime lifecycle, EOF stop, multi-camera isolation, writer throttling,
  FK fallback). Real smoke skipped unless weights + demo clip are present.
- `tests/test_edge_api.py` — PG end-to-end API tests: status/start/stop, MJPEG
  stream (200, content-type, drains to EOF), unknown-camera 404, and observations
  persisted **without inventory mutation**.

### Real-model end-to-end (YOLO11n + ByteTrack → PG)
- Ran the full person pipeline against a real store video and observed observation
  rows written to PostgreSQL (`observations`), with camera-FK fallback for non-DB
  camera ids. Verified via the opt-in `real_ai` smoke test (7.9 s).

### Performance benchmark (person-only, CPU, 6 s × 30 fps 1268×646 source)
| Metric | Value |
|--------|-------|
| Processed | 46–85 frames (load-dependent) |
| Throughput | **~6–11 fps (≈7 fps typical)** |
| Drop factor | ~0.53–0.74 |
| Obs persisted (throttle 0, one run) | 350 rows |

Honest read: on a 30 fps source the runtime is CPU-bound and processes about a
quarter of real-time, dropping what it cannot keep up with. Existing `real_ai`
smoke also ran at ~5–8 fps on the prior clip.

### Frontend
- **43 tests pass** (`npm test`), **production build passes** (`npm run build`).

### Offline
- `app/edge` contains no HTTP/socket/urlopen/urllib calls (code scan clean).
- Person + product/shelf models load from local `models/*.pt`.
- **Caveat (documented):** PaddleOCR downloads its models once on first init
  (cached in `~/.paddleocr`); afterwards it runs offline. A never-initialized,
  no-internet machine cannot bootstrap OCR.

## Root-cause fixes landed this milestone
- Writer `NoneType` call in background threads → `get_session()` auto-init.
- File sources bursting → FPS-paced capture period.
- Pytest hangs on camera start/stop → close writer sessions each batch (leaked
  connections were blocking `drop_all` teardown).
- Camera registry path resolution for real weights → relative imports + correct
  `_PROJECT_ROOT`.

## Not built (explicitly out of scope)
Supabase / cloud sync / WhatsApp / SMS / auto-billing / AI bills /
auto-reconciliation / FEFO / AI alerts / face recognition / biometrics /
distributed infra / Kubernetes / microservices / external object storage.
No new SQLite business dependency; no cloud dependency.

## Next
M14 (per roadmap) — this milestone is complete and verified.