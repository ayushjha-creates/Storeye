# M27 — Real-World Reliability Audit

Read-only audit performed before any M27 code changes. Purpose: establish
exactly what exists today, locate the real-world failures, and decide the
minimal defensible fixes. Nothing here is aspirational — every claim is tied to
a file/line or a measured value.

## 0. Summary of real-world failures

| # | Observed | Root cause(s) found | Severity |
|---|----------|---------------------|----------|
| 1 | One person produced ~57 journeys | Same-camera re-acquisition is forbidden + ByteTrack id churn | Critical |
| 2 | Shelves produce no intelligence | Region coordinates authored in 0–100 space, real detections in pixels; product pipeline aimed at the wrong camera; no region-config UI | High |
| 3 | Biscuit not a PRODUCT | The installed product model has **no biscuit class**; catalog mapping is exact-string; inference is skipped when aimed at a non-product camera | High |
| 4 | Phone→USB scan unusable | No capture/upload surface; jobs never closed after confirm; FAILED jobs unrecoverable; photo never shown | High |
| 5 | Camera setup is 1-camera | No camera provisioning UI; runtime never reads cameras from the DB; no N-camera/health model | High |

## 1. Current camera architecture

- `Camera` (`backend/app/models/camera.py:18-30`) is pure config metadata:
  `store_id, name, location, camera_type ("usb"|"file"|"rtsp"), is_active,
  config(JSON)`. **No zone/health/count columns. No camera-count limit
  anywhere.**
- CRUD: `backend/app/api/routers/cameras.py` (`GET/POST/GET{id}/PATCH/DELETE`),
  STAFF+ reads / MANAGER+ writes. `config` validated by
  `backend/app/schemas/camera.py:37-76`.
- `EdgeRuntime` (`backend/app/edge/runtime.py:33-211`) is a process-wide lazy
  singleton (`registry.py:19-26`). It keeps `_workers: {camera_id: CameraWorker}`
  (one worker per camera) and a shared `_reid` identity manager.
- **The runtime never reads cameras from PostgreSQL.** Registration happens
  lazily in `backend/app/api/edge_api.py:_ensure_configured` (100-113), called by
  edge status/start/stop/stream. No supervisor, no auto-start, no reaction to
  PATCH/DELETE.
- Frontend `frontend/src/pages/Cameras.tsx` already renders N cameras (`map` at
  139). **There is no add/edit camera UI** — the empty state tells the user to
  `POST /api/cameras` (`Cameras.tsx:132-136`).

## 2. Current AI pipeline

Per camera, `CameraWorker` (`backend/app/edge/workers.py`) runs a capture thread
+ an inference thread over a bounded deque, then `EdgePipeline.process()`
(`backend/app/edge/pipeline.py:104-123`) runs the enabled taps and returns
`(events, None)`; the worker annotates the frame itself.

- Person tap: `pipeline.py:128-157` → `PersonTrackerModel.track_frame`.
- Product tap: `pipeline.py:294-311` → `ProductDetectorModel.detect_frame`.
- OCR tap: opt-in, `pipeline.py:313-356`.
- Events are persisted by `ObservationWriter` (`edge/observation_writer.py`),
  which the worker now keeps alive across frames (one writer/session per worker;
  closed on `stop()`). Observations land in the `observations` table.

## 3. Current detector classes (MEASURED)

Loaded directly from the checkpoints on disk:

- `models/yolo/yolo11n.pt` — COCO, 80 classes, includes `person` (id 0). Used
  for person detection + ByteTrack. **Not a grocery/product model.**
- `models/shelf/shelf_model.pt` — 55-class fine-tuned retail detector, used as
  the "product" model (`edge/models/product_detector.py:26-48`,
  `vision/shelf_detector.py`). Full measured class list:
  Complan (5), Everyuth face packs/lotions (16), Glucon D (6), Nutralite (8),
  Nycil (1), Sugar Free (13), Sugarlite (1).

**There is no `biscuit` / `Parle` / `Britannia` / generic `package` class.** A
real biscuit packet is out-of-distribution for the product model. This is the
honest reason "biscuit isn't detected" — not OCR, not a broken pipeline.

## 4. Current tracking pipeline

- ByteTrack via Ultralytics persistent API: `vision/tracker.py:139-149`
  (`model.track(..., persist=True, tracker="bytetrack.yaml", classes=[0])`).
- One `PersonTracker` per camera, created in `registry.new_person_tracker`
  (`registry.py:63-69`), held for the worker's lifetime. Tracker state is
  camera-local (test: `test_multi_camera_each_has_own_tracker`).
- Installed ByteTrack defaults: `track_high_thresh 0.25`, `track_low_thresh 0.1`,
  `new_track_thresh 0.25`, `track_buffer 30`, `match_thresh 0.8`.
- Untracked boxes (`track_id < 0`) are dropped (`edge/models/person_detector.py:46-48`).

## 5. Current Re-ID pipeline

- `GlobalIdentityManager` (`services/journeys/reid/association.py:45-276`),
  constructed once per runtime (`runtime.py:69-89`), shared by all cameras.
  Provider `torch` = ResNet18-ImageNet 512-d features (`reid/providers.py`).
- `combined = cosine(appearance) × time_factor`, accept if
  `>= similarity_threshold (0.72)` (`reid/matcher.py:51-76`).
- Candidate filters (`_best_candidate`, `association.py:242-268`): store
  isolation, **`rec.last_camera_id == sighting.camera_id → continue`
  (line 254-255)**, time gap, camera transition graph.
- Same `(camera, track)` always fast-paths to its cached gid
  (`association.py:131-136`).

**The critical defect:** the unconditional same-camera skip means any *new*
ByteTrack id on the same camera can never match the person's earlier identity.
On a single-camera deployment this guarantees a new global id per track
re-acquisition.

## 6. Current journey lifecycle

- Model `GlobalPersonSession` (`models/journeys.py:50-67`): one row per
  `(store_id, global_person_id)`; `status`, `confidence`, `first_seen_at`,
  `last_seen_at`, `expires_at`, `camera_count`.
- `JourneyService.ensure_global_person` (`journey_service.py:61-103`) creates a
  row **only when the gid is new**, else refreshes `last_seen_at`. Called from
  `upsert_track_association` / `record_transition` / `open_zone_visit`.
- The writer persists `TRACK_ASSOC` events
  (`observation_writer.py:271-290`); the pipeline emits one whenever a track's
  gid changes (`pipeline.py:204-217`).
- A PERSON observation alone does NOT create a journey — but because each new
  track gets a fresh gid (§5), each track effectively creates one. The journey
  table is a near-1:1 mirror of ByteTrack track births.

## 7. Current shelf architecture

- Shelf "regions" are configured per camera in `camera.config.shelf_regions`
  as `{code, label?, bbox:[x1,y1,x2,y2]}` (`shelf_intelligence.py:123-153`).
  **There is no shelf detector** — shelf intelligence is
  region-configuration + spatial association of product observations.
- Occupancy = Σ intersection-area / region-area, centre-point association
  (`shelf_intelligence.py:307-411`), states `UNKNOWN / EMPTY_VISIBLE /
  LOW_VISIBLE / NORMAL_VISIBLE`. No temporal smoothing.
- Contradictions found: demo/seed regions are authored in a 0–100 coordinate
  space (`seed_demo.py:192-198`) while the real detector emits pixel
  coordinates; the demo "Shelf Camera" is a `camera_type="file"` camera with no
  source; `_config_from_camera` never forwards `shelf_regions`
  (`edge_api.py:88-97`); `_shelf_lookup` has no `ORDER BY` and duplicate shelf
  codes are ambiguous (`shelf_intelligence.py:262-272`).

## 8. Current product detection architecture

- `ProductDetectorModel.detect_frame` → `ShelfDetector.detect` → 55-class YOLO,
  `imgsz=640`, `conf` default 0.25 (`edge/models/product_detector.py:29-48`,
  `shelf_detector.py:151-176`).
- `_product_tap` emits `PRODUCT` events with `class_name`.
- Product Intelligence maps `class_name → Product` **only via an explicit
  `Product.ai_classes` list (exact string match)** (`product_intelligence.py:181-186`,
  `shelf_intelligence.py:293-305`). Unmapped classes are reported as
  "Unmapped AI class — assign Product.ai_classes" — they are never guessed.

## 9. Current mobile intake architecture (M25)

- Watcher polls `<INTAKE_ROOT>/intake` every 1s
  (`services/mobile_intake/intake_watcher.py:158-186`), stability-checks,
  sha256-dedupes, runs the M17 scanner (barcode + PaddleOCR + ExpiryParser),
  and produces a `REVIEW_REQUIRED` job. Human review + confirm happens on M17
  `/api/batch-intake/confirm` → `BatchService` + `InventoryService` (atomic).
- **Gaps:** no phone capture/upload surface (only a file input); confirmed jobs
  are never closed by the UI; FAILED jobs have no rescan button; the stored
  photo is never shown; watcher scan is not store-scoped; watcher lifecycle is
  a silent startup side effect.

## 10. Current camera configuration architecture

- DB-driven camera records exist and support N cameras; the frontend grid
  already renders N. What is missing is a **provisioning UI**, a
  **runtime supervisor** that reconciles the DB with the runtime, and a real
  **health state machine** (`CONNECTED/STARTING/RUNNING/DEGRADED/OFFLINE/ERROR`
  does not exist; health is an ad-hoc frontend derivation plus a stale-
  observation insight proxy).
- `connection_ok = True` is set immediately after `source.open()`
  (`workers.py:118`); `stop()` clears `last_frame_at` (`workers.py:158`);
  `RTSPSource.open()` always raises (`edge/camera.py:207-213`).

## 11. Known limitations

- Product model is brand-specific FMCG, not a general grocery/package detector.
- No temporal smoothing for shelf occupancy.
- Re-ID features are ImageNet ResNet18, not Re-ID-trained; cross-camera
  precision is unproven on real footage.
- No physical USB hand-off has been verified (M25 doc §Known limitations).
- Development `--reload` restarts reset in-memory tracking/identity state,
  producing new journeys per restart (expected, but worth documenting).

## 12. Recommended fixes (in priority order)

1. **Person identity/session lifecycle (M27 Phase 2-5):** allow *guarded*
   same-camera re-acquisition in `GlobalIdentityManager` so a lost-then-found
   local track keeps its global id and journey, while concurrent same-camera
   tracks are still never merged. Add tests for same-track, re-acquisition,
   concurrent-reject, and distinct-people. Journey creation stays
   "one row per unseen gid"; repeated sightings refresh `last_seen_at`.
2. **Model honesty (Phase 7-9, 33):** publish
   `docs/model_capabilities.md`; introduce a `PRODUCT_CANDIDATE`/Unknown-product
   path so unmapped classes are shown as "Unknown product — map to catalog",
   never guessed; keep the barcode → catalog → visual-mapping hierarchy.
3. **Shelf (Phase 10-11):** normalise region authoring, forward
   `shelf_regions` into the runtime config, add deterministic shelf lookup,
   temporal smoothing, and a "Configure shelf region" UI that clearly says
   *configured*, not *auto-detected*.
4. **Mobile intake (Phase 12-16):** add a usable capture→folder→review flow,
   close jobs after confirm, expose rescan, show the photo.
5. **Cameras (Phase 17-21):** provisioning UI, runtime↔DB supervisor, explicit
   health enum, capacity guardrails, N-camera dashboard driven by real APIs.
6. **Real vs demo + reset tooling (Phase 6, 27-28):** safe, confirmation-gated
   dev resets; every dashboard labels REAL vs DEMO.

The rest of M27 implements these; this document is the frozen "before" state.
