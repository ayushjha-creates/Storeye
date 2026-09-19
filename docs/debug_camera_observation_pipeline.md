# Debug log: camera → observation pipeline

## 1. Symptom

On the real USB camera **"Entrance Cam"** (`camera_id =
15a3bd12-a138-425d-b109-fd2237878282`, `store_id =
be6ee182-8b5b-40d5-86f8-bf4aaaf47b92`, `camera_type = usb`) the camera detail
page showed a **live green person bounding box** in the MJPEG stream, but the
AI panels reported the wrong picture:

- People detected: **0**
- Products detected: **0**
- Tracks: **0**
- FPS: **0.0**
- Recent detections timeline: **empty**

A live bounding box means the detector, tracker and annotator are all running.
So the task was to find **where the real detection was lost** — not to fake
data, add demo rows, or shortcut the UI.

## 2. Constraints honoured

- No fabricated observations, no inserted fake detections, no counter edits.
- No model swap, no download, no ByteTrack removal, no PostgreSQL bypass.
- No frontend-side inference.
- M13–M26 behaviour (Edge AI, Camera Dashboard, Product/Shelf Intelligence,
  Alerts, Smart Receiving, Demo, Journeys, Store Intelligence, Scenario Engine,
  Production Hardening, Deployment, USB Intake) preserved.

## 3. Pipeline map (where data can be lost)

```
CameraSource.read()            app/edge/camera.py
  -> CameraWorker._capture_loop       (bounded deque, drops oldest)
  -> CameraWorker._infer_loop
     -> EdgePipeline.process()        app/edge/pipeline.py   (YOLO11n + ByteTrack)
        -> list[EdgeEvent]            PERSON / PRODUCT / TEXT / EXPIRY_METADATA
     -> annotate_frame()              app/edge/annotator.py  (the green box)
     -> ObservationWriter.write()     app/edge/observation_writer.py (throttle)
        -> ObservationService.record_*   (PostgreSQL `observations`)
     -> CameraWorker.status()         counters/status
GET /api/observations(+summary)       app/api/routers/observations.py
frontend CameraDetailPage             frontend/src/pages/CameraDetail.tsx
```

The live box is drawn from `EdgeEvent`s at the annotate step, which is
**upstream** of persistence and **upstream** of the HTTP API. A live box with
zero UI counts therefore points at either persistence/API or the frontend — not
the detector.

## 4. Reproduction

1. Start the backend (`./scripts/start.sh --backend-only`) and the frontend.
2. Log in, open the "Entrance Cam" detail page, click **Start**.
3. Observe a live green box while every AI panel stays at 0.

## 5. Evidence (read-only checks)

**PostgreSQL — persistence works.** `observations` (not `ai_observations`) held
**1605 rows for this camera**: 1557 `PERSON`, 48 `PRODUCT`, 7 distinct
`track_id`s, newest `2026-09-18T01:42:26+05:30`. The writer path is real.

```sql
SELECT observation_type, count(*) FROM observations
WHERE camera_id = '15a3bd12-a138-425d-b109-fd2237878282'
GROUP BY observation_type;
```

**HTTP API — reads work.** Authenticated calls returned the same data:

- `GET /api/observations?camera_id=…&limit=200` → `total: 1605`, 200 items.
- `GET /api/observations/summary?camera_id=…&hours=24` → `total: 1605`,
  `by_type {PERSON: 1557, PRODUCT: 48}`, `distinct_tracks: 7`.

**Edge status — runtime ran.**

- `GET /api/edge/cameras/…` → `running: false`, `fps: 3.58`,
  `frames_captured: 6467`, `frames_processed: 1593`,
  `frames_dropped: 4874`, `observations_written: 1621`, `last_frame_at: null`.

**Backend log — clean run, no crash.**

- `01:38:39` first start failed (`OpenCV: camera failed to properly initialize!`).
- `01:38:50` retry succeeded (`Opened usb source=0 (1920x1080 fps=15.00)`).
- `01:42:27` `Stopped camera worker` — a deliberate `stop()`, not a crash.

Conclusion: detection, tracking, persistence and the API were **all healthy**.

## 6. Root cause (why the UI showed zeros)

`frontend/src/pages/CameraDetail.tsx` loaded everything **once** on mount. The
MJPEG `<img>` stream keeps updating on its own, but observations, summary and
edge status were a one-shot snapshot taken *before* detections ramped up. There
was no polling interval anywhere in `CameraDetail.tsx` or
`components/camera/*`. Clicking start/stop called `refreshEdge` only, which did
**not** reload observations or the summary.

So the counts were never "lost" — the page simply never asked again.

## 7. Secondary defect found (real, fixed)

`CameraWorker._write_events` created an `ObservationWriter` and then **closed it
in a `finally` after every call**. `ObservationWriter` keeps its per-kind
throttle state in instance fields (`_last_write`, `min_observation_gap_seconds`),
so disposing it each frame reset the throttle to zero and PERSON rows were
written almost every frame.

Evidence: 1557 PERSON rows in ~3.5 minutes ≈ **7/s**, versus the intended
`min_observation_gap_seconds = 2.0` (≈ 0.5/s). This is connection churn plus row
flood on a continuous camera.

## 8. Fix

**Frontend — live polling (`CameraDetail.tsx`).**

- Added `LIVE_REFRESH_MS = 2000`.
- Added `refreshLive()`: fetches observations + summary + edge status only
  (the heavy intelligence/reconciliation/alert reads stay on the initial load).
- A `setInterval(refreshLive, LIVE_REFRESH_MS)` runs after the initial load and
  is cleared on unmount; failures are swallowed so the page never blanks.
- Starting/stopping the camera calls `refreshLive()` immediately; the poller
  then keeps the panels current.

**Backend — writer lifetime (`app/edge/workers.py`).**

- `_write_events` now keeps the writer alive across frames, so throttle state
  persists.
- New `_close_writer()` closes and drops the writer on `stop()` or after a write
  failure, so no DB session or connection outlives the worker.
- Injected writers (tests) are never closed (`_writer_owned` guard preserved).
- Added DEBUG-only, throttled diagnostics in `_process_one` (every 30th frame):
  frame index, infer ms, event/person/product counts, track ids, written total.
  No images are logged.

## 9. Verification

- The same DB/API queries now track the page: while running, "Recent detections"
  and the stat panels advance every ~2s without a manual reload.
- Writer throttle restored: PERSON writes are gated by
  `min_observation_gap_seconds` again instead of one-per-frame.
- Backend: full suite **440 passed** (`backend/.venv/bin/pytest -q`), including
  new `test_worker_reuses_writer_across_frames_and_closes_on_stop`.
- Frontend: **126 passed** (`npx vitest run`), `npx tsc -b` clean,
  `npm run build` green, including new
  `polls live so newly-detected observations appear without a manual refresh`.
- `alembic check` clean (no schema change was needed).

## 10. What was deliberately NOT changed

- YOLO11n weights, thresholds, ByteTrack, Re-ID, M17/M25.
- The `observations` persistence model and the read-only observation API.
- No `ai_observations` table, no demo/fake data.
- No frontend inference or hard-coded detections.

## 11. Prevention / regression guards

- `backend/tests/test_edge_ai.py::test_worker_reuses_writer_across_frames_and_closes_on_stop`
  fails if the writer is recreated per frame or leaked past `stop()`.
- `frontend/src/pages/CameraDetail.test.tsx::polls live so newly-detected
  observations appear without a manual refresh` fails if polling is removed.
- Debug tip: set the edge logger to DEBUG
  (`storeye.edge.worker`) to see the per-30-frame detection summary.

## 12. Files touched

- `frontend/src/pages/CameraDetail.tsx` — polling + refresh on start/stop.
- `backend/app/edge/workers.py` — persistent writer, `_close_writer`, DEBUG log.
- `backend/tests/test_edge_ai.py` — writer-lifetime regression test.
- `frontend/src/pages/CameraDetail.test.tsx` — polling regression test.
- `docs/debug_camera_observation_pipeline.md` — this document.
