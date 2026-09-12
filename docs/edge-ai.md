# Edge AI Runtime — M13

**Status:** Implemented and verified
**Design principle:** Edge-first / offline-first. All inference runs locally on the
device. Nothing is uploaded, and no cloud endpoint is called. PostgreSQL stays the
single authoritative database.

---

## 1. What it is

A real-time, multi-camera image-analysis runtime that plugs the existing vision
stack (YOLO11n person detection + ByteTrack tracking, shelf/product detection, and
PaddleOCR + ExpiryParser) into the Storeye backend. Each configured camera gets a
dedicated worker that captures frames, runs the enabled pipelines on a bounded
"latest frame wins" queue, emits typed `EdgeEvent`s, annotates frames for a live
MJPEG stream, and persists observations to PostgreSQL **without touching
inventory, batches, bills or sales**.

## 2. Architecture

```
Camera source (file / webcam / RTSP)
      │  capture thread (paced; drops stale frames)
      ▼
+-----------------------------+
| CameraWorker (per camera)   |   capture queue (bounded, newest wins)
|  capture thread ────────────┼──▶ inference thread
|  inference thread ──────────┼──▶ EdgePipeline (optional modules)
|  writer thread (throttled)  |      person(track)  · product(shelf)  · ocr(expiry)
|                 │           |      └── ModelRegistry (singleton thread-safe)
+-----------------------------+      └── injectable fakes in tests
      │
      ▼  EdgeEvent list                                   ObservationWriter
+-----------------------------+   ─────────────────────▶  ObservationService
| EdgeRuntime (owns workers)  |   (per-kind throttle,      PostgreSQL
|  start/stop/status/remove   |    FK fallback, uuid guard)  │
+-----------------------------+                             ▼
      ▲                                                    observations
      │ FastAPI `/api/edge/*` + MJPEG `/api/edge/stream/{id}`
      ▼
React CameraDetail / Cameras (status pill, Start/Stop, live stream)
```

Key decisions:

- **Multi-camera** = one `CameraWorker` thread-set per camera, each with its own
  `EdgePipeline` instance so tracker state (ByteTrack IDs) is isolated per camera.
- **Bounded queue, newest-frame-wins** — when real inference is slower than the
  source, stale frames are dropped instead of backing up memory.
- **Camera source pacing** — file sources replay at their nominal FPS so demo
  videos behave like live cameras; webcam/RTSP read as fast as the device delivers.
- **Thread-safe model registry** — detectors/OCR are created once and shared; a
  fresh person tracker is created **per camera** so track IDs never cross cameras.
- No business-side effects: the runtime may only write `observations`; it never
  auto-mutates inventory/batches/bills/sales.

## 3. Modules

| Area | File | Notes |
|------|------|-------|
| Runtime | `backend/app/edge/runtime.py` | worker lifecycle, config, status |
| Workers | `backend/app/edge/workers.py` | capture/inference/annotate/write threads |
| Camera sources | `backend/app/edge/camera.py` | `file` / `webcam` / `rtsp` + `create_camera_source` |
| Pipeline | `backend/app/edge/pipeline.py` | confidence gate, OCR cadence, event emit |
| Models | `backend/app/edge/models/` | person (YOLO11n + ByteTrack), product/shelf, OCR+expiry adapters, injectable fakes |
| Registry | `backend/app/edge/models/registry.py` | shared singletons, local weight paths, per-camera trackers |
| Events | `backend/app/edge/events.py` | typed kinds: `PERSON / PRODUCT / TEXT / EXPIRY_METADATA` |
| Writer | `backend/app/edge/observation_writer.py` | persistence + throttling + FK fallback |
| API | `backend/app/api/edge_api.py` | control + MJPEG streaming |
| Frontend | `frontend/src/lib/api/edge.ts`, `CameraDetail.tsx`, `Cameras.tsx` | status/controls/stream |

## 4. Observation persistence rules

- Mapped through the existing `ObservationService` (`record_person_observation`,
  `record_product_observation`, `record_text_observation`,
  `record_expiry_metadata_observation`) — never direct table writes.
- Per-kind **throttle** (`min_observation_gap_seconds`) so repetitive detections do
  not flood the DB (default 2 s).
- `store_id` / `camera_id` are sanitized with `_uuid_or_none`; if the camera FK does
  not match a real `cameras` row the observation is persisted with `camera_id=NULL`
  rather than dropped.
- **Explicit class→product mapping (M15):** PRODUCT observations are stamped with a
  `product_id` only when the class is declared on `Product.ai_classes` (deterministic
  mapping, first product by SKU order per class). Unmapped classes keep
  `product_id=NULL` and are surfaced upstream as "Unmapped AI class" — the runtime
  never guesses a mapping.
- Writer sessions are created via `get_session()` (auto-initializes the engine) and
  closed after every batch so background threads never leak connections.

## 4.1 Intelligence (M15)

The observation stream feeds read-only intelligence services —
`app/services/intelligence/` (product comparison, shelf occupancy/states, possible
misplacement, AI summary) exposed via the `/api/intelligence/*` read-only endpoints.
See `docs/milestone_15_product_shelf_intelligence.md`. The intelligence layer is
informational only and never mutates inventory/batches/bills/sales.

### 4.2 Alerts (M16)

The intelligence layer feeds a persistent, offline-first **alert system** —
`app/services/alerts/` (`AlertRuleEngine` over M15 intelligence + persisted
reconciliation + camera heartbeat proxy; `AlertService`) exposed via `/api/alerts/*`
(list/create/get/patch-metadata + `acknowledge|resolve|dismiss` lifecycle +
`POST /api/alerts/evaluate` to generate). Alerts are informational and actionable,
never mutate inventory/batches/bills/sales, and evaluation reuses M15/M13 results
without re-running YOLO/OCR. See `docs/milestone_16_alerts.md`.

### 4.3 OCR repositioning (M17) — close-up intake is the reliable path

M17 stopped relying on the continuous-camera OCR tap for anything real and added a
**close-up Smart Batch Receiving** path as the reliable way batch metadata enters
stock. See `docs/milestone_17_smart_batch_receiving.md`.

| Pipeline | Where OCR runs | Role |
|----------|----------------|------|
| **Smart Batch Receiving** (`app/services/batch_intake/`) | Close-up package photo, on demand | **Production path**: barcode (identity) + PaddleOCR text → `ExpiryParser` → editable candidate → human-confirmed atomic batch+stock commit |
| **CCTV text tap** (`app/edge/pipeline.py` `_ocr_tap`) | Continuous cameras | **Experimental / opt-in** (`PipelineConfig.ocr = False` default). Reads text and writes `TEXT` / `EXPIRY_METADATA` **informational observations only** — never mutates inventory |

The two share the same `OCRService` and `ExpiryParser`, but the edge tap stays
bounded to observation-writing: a ceiling camera cannot reliably read a printed
`EXP:`/`MFG:`/`BATCH:`/`MRP:` label at distance, so it never pretends to.

## 5. HTTP API

All under `/api/edge`. Prefix: configured cameras must already exist in the
`cameras` table; the API reads `camera.camera_type` and `camera.config`.

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/edge/status` | GET | runtime summary + worker status map |
| `/api/edge/cameras` | GET | configured cameras with status |
| `/api/edge/cameras/{id}` | GET | per-camera status (running, frames, fps) |
| `/api/edge/cameras/{id}/start` | POST | start worker (409 if it fails) |
| `/api/edge/cameras/{id}/stop` | POST | stop worker |
| `/api/edge/stream/{id}` | GET | annotated MJPEG; ends when worker stops |

## 6. Frontend integration

- `CameraDetail.tsx`: AI badge (`RUNNING / READY / STOPPED`), Start/Stop via the
  edge API, "Edge runtime X fps" when running, and an MJPEG `<img>` that prefers the
  edge stream while running and falls back to `camera.config.streamUrl`.
- `Cameras.tsx`: per-camera `LIVE / READY / STOPPED` pill and `RUNNING / IDLE` AI
  badge; live fps + observation counters when running.
- All edge calls are **best-effort** — if the edge endpoints 500 or the backend is
  unreachable the page still renders.

## 7. Testing

- **Fast fake-model tests** (no models, no network): `backend/tests/test_edge_ai.py`
  — event emission, confidence gating, OCR cadence, runtime lifecycle, EOF
  auto-stop, multi-camera isolation, remove, writer throttling, FK fallback.
  Markers `no_db`.
- **PG API tests**: `backend/tests/test_edge_api.py` — status, start/stop,
  MJPEG stream, unknown-camera 404, and "observations persist without inventory
  mutation".
- **Opt-in real model smoke**: `test_real_person_smoke` (marker `real_ai`, skipped
  unless `models/yolo/yolo11n.pt` and `data/tests/tracking/test_people.mp4` exist)
  and `test_real_shelf_product_smoke` (shelf product detection across
  `data/datasets/shelves/images/`, requires `models/shelf/shelf_model.pt`).
  Run with `pytest -m real_ai`.

## 8. Performance (honest, on this Mac, CPU inference)

Measured against a 6 s, 30 fps 1268×646 store video (`data/tests/tracking/
test_people.mp4`), person tracking only, writing to PostgreSQL:

| Metric | Observed |
|--------|----------|
| Frames in source | 180 |
| Frames processed | 46–85 across runs (CPU-bound variance) |
| Frames dropped (overrun) | 95–134 |
| Wall time to EOF | ~7.6 s (video is 6 s → slower than real-time) |
| Throughput | **~6–11 fps** (≈7 fps typical) |
| Drop factor | ~0.53–0.74 |
| Observations persisted | hundreds (throttle=0) |

The system is honest about throughput: on a 30 fps source it processes at roughly a
quarter of real-time and drops the frames it cannot keep up with. Enabling OCR
(heavy) or running many cameras lowers this further. Expect near-real-time only on
the smallest inputs; frame-rate-limited webcams (≤ ~8 fps) track live.

## 9. Offline behaviour

- `app/edge` performs **no network I/O** (verified by code scan): person tracking and
  product/shelf detection load local `.pt` weights
  (`models/yolo/yolo11n.pt`, `models/shelf/shelf_model.pt`) and run entirely offline.
- **OCR caveat:** PaddleOCR fetches its detection/recognition models once on first
  initialization (cached under `~/.paddleocr`). After that it runs offline. A truly
  cold machine with no internet and an empty cache cannot bootstrap OCR — a known,
  documented limitation (the rest of the pipeline is unaffected).
- **TODO — future offline-deployment milestone:** for fully offline installs, vendor /
  pre-package the PaddleOCR model files (`~/.paddleocr`) at build time so a
  never-initialized machine without internet can still enable OCR.

## 10. Known limitations

- CPU-bound throughput (~7 fps person-only); no GPU/MPS backend for Paddle.
- PaddleOCR first-run download requires internet (see §9).
- MJPEG is per-camera and ends when the worker stops.
- Webcam capture is implemented but untested on dedicated hardware; automated
  tests use video files by design.