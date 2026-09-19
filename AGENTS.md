# Status Summary

## Objective
- **M32 — Product & Shelf Detection That Actually Works** (DONE code+tests,
  real-model inference verified on this Mac; physical store-camera verification
  pending a human): the user said "shelf detection is still not working, and
  also product detection — anyhow make it do so." Root cause: the only product
  model was a 55-class fine-tuned FMCG checkpoint with **no biscuit/general
  grocery class**, there is **no shelf-detection model**, and the live overlay
  rendered **pixel** bboxes as if normalized 0–100. Fix = default to
  **YOLO-World open-vocabulary** detection driven by the store's own prompts /
  catalog, carry a normalized `bbox_norm` for correct overlay rendering, resolve
  prompt names to the catalog via the existing conservative matcher, fail soft
  (missing weights only disable the product tap), operator UI for detector +
  prompts. Hard constraints unchanged: no fabricated detections/counters, no
  cloud AI, no face recognition, offline-first, local PostgreSQL authoritative,
  no frontend-side inference, demo mode deterministic, real model limits
  documented honestly. Docs: `docs/milestone_32_product_shelf_detection.md`,
  `docs/model_capabilities.md`.
- **M31 — SMS Bill Receipts (MSG91)** (DONE code+tests, live-send pending a
  human at the store; docs in `docs/milestone_31_sms_bill_receipts.md`): save
  a manual bill for a customer with a phone → auto-queue a **text receipt**
  into a local `sms_messages` outbox → daemon worker sends via MSG91 with
  retry backoff → honest QUEUED/SENDING/SENT/FAILED status surfaced in
  Billing + resend for FAILED only. Billing is NEVER blocked or slowed by SMS
  (enqueue runs after commit, own transaction, swallows all errors).
- **M27 — Real-World AI Reliability & Multi-Camera System** (ACTIVE): fix the
  physical-camera failures with REAL data — one person counted as ~57 journeys,
  shelf intelligence not working, biscuit/product not detected, mobile USB
  scanning unusable, and single-camera-only setup → build 1/2/3/4+/N camera
  configuration. User-mandated order: **tracking/journey first, then
  product/shelf, then mobile intake, then multi-camera**. Hard constraints: no
  fabricated detections/counters, no cloud AI, no face recognition, offline-first,
  local PostgreSQL authoritative, no frontend-side inference, keep demo mode
  deterministic and clearly separated, document real model limits honestly.
- **Camera → observation pipeline debug** (COMPLETE): the real USB camera
  "Entrance Cam" showed a live green bounding box but the dashboard read 0
  people / 0 products / 0 tracks / 0.0 FPS. Prove where the real detection was
  lost and fix only the root cause — no fake data, no model/ByteTrack removal,
  no frontend-side inference, no faking counters. Must preserve M13–M26.
- **Authentication & Authorization milestone** (COMPLETE, docs in
  `docs/authentication.md`): offline-first Argon2id auth + server sessions in
  HttpOnly cookies + RBAC + per-store isolation.
- **M29 — Cascaded edge pipeline + hot person cache + minimal durable
  analytics** (DONE code+tests, hardware verification pending): normalize
  journey/product/expiry outputs, cut the Re-ID compute cost, and keep
  on-device latency bounded. Constraints (unchanged): offline-first, Redis NOT
  mandatory, do NOT swap YOLO11n before benchmarking, keep ByteTrack, no
  faces/raw frames/embeddings in PostgreSQL, no fabricated perf numbers.
- **M30 — Periodic Shelf-Occupancy Monitoring** (DONE code+tests, hardware
  verification pending): wall-clock snapshot cadence (default 30 s) → 4-state
  region fill (EMPTY/LOW/MEDIUM/FULL) with a person-occlusion gate, snapshots
  as observations + on-disk JPEGs (root-relative, retention 7 d), user-decided
  **PG authoritative + in-memory Layer-A mirror**, cache-first read APIs, and a
  ShelfMonitor card on the camera page. Same hard constraints (no fabricated
  fill, no cloud, offline-first).

## Current State
**M32 product & shelf detection DONE — backend 587 passed / frontend 164 passed;
gates green; real YOLO-World inference verified on this Mac; physical-camera
verification pending a human:**
- **Detector**: new `backend/app/services/vision/world_detector.py`
  (`WorldProductDetector` wrapping `ultralytics.YOLOWorld`; `set_prompts`
  encodes text via CLIP; `detect` reuses the `Detection`/`DetectionResult`
  shape; empty prompts = concrete no-op). Weights
  `models/shelf/yolov8s-worldv2.pt` (~25 MB, local), CLIP text encoder
  `backend/weights/clip/ViT-B-32.pt` (~338 MB, **gitignored**, downloaded once
  by Ultralytics, SHA-256 verified). Adapter `WorldProductDetectorModel` in
  `app/edge/models/product_detector.py`; registry
  `new_product_detector(detector="world"|"shelf", prompts, conf)` caches
  YOLO-World by `(path, prompt_tuple)` so identical vocabularies share one model.
- **Config/runtime/API**: `PipelineConfig.product_detector` (`"world"` default)
  + `product_prompts`, validated (`world|shelf`). `EdgeRuntime.add_camera`
  builds the per-camera product model **fail-soft** (missing weights disable
  only the product tap). `_config_from_camera(cam, db)` forwards operator
  prompts, else derives them from the store catalog (`ai_classes` → `brand` →
  `name`, deduped, cap 40). Camera schema validates the new keys (flat+nested).
- **Normalized overlay boxes**: person/product events carry `bbox_norm`
  ([x1,y1,x2,y2] 0..1); ObservationWriter stores it in `details["bbox_norm"]`
  and resolves open-vocab prompt names to the catalog via `ProductNameMatcher`.
  Pixel `bbox` (M15/M30) unchanged.
- **Frontend**: `DetectionOverlay` prefers `details.bbox_norm` (percentages) with
  legacy 0–100 `(x,y,w,h)` fallback; `Cameras.tsx` adds Product detector
  selector + Product prompts field persisted in nested `pipelines`.
- **Tests**: `tests/test_world_detector.py` (11), pipeline `bbox_norm`, writer
  `bbox_norm`+name fallback, `_config_from_camera` prompts/derivation, camera
  schema validation, runtime fail-soft product model;
  `DetectionOverlay.test.tsx` (3) + Cameras persistence. `alembic check` clean.
- **Docs**: `docs/milestone_32_product_shelf_detection.md` written;
  `docs/model_capabilities.md` updated (sections 3a/3b, summary table, 6, 8).

**M31 SMS receipts DONE — backend 568 passed / frontend 160 passed; gates green; live MSG91 send pending a human:**
- **Outbox**: `sms_messages` rows (`status` QUEUED/SENDING/SENT/FAILED, `mobile`+
  `message` snapshotted, `bill_id` FK **SET NULL**, index
  `ix_sms_messages_store_status_due`). Migration `e7a3c5f1b2d8` (down
  `d5e8b0c2e4f6`); `alembic check` clean; dev `storeye` DB upgraded.
- **Worker**: daemon `SmsWorker` thread in the FastAPI process (lifespan
  start/stop); claims due rows (`for_update SKIP LOCKED`) → `process_pending`
  → SENT on ack, QUEUED+backoff on retryable error (60s doubling, cap 3600s,
  `SMS_MAX_ATTEMPTS`), FAILED otherwise; stale SENDING (`>SMS_STALE_CLAIM_SECONDS`) re-claimed.
- **Gateway**: MSG91 legacy `sendhttp.php` via httpx; ack = body contains
  `type:success`; `SmsGatewayNotConfigured` (no auth key) → terminal FAILED,
  `SmsGatewayError` → retryable. `SMS_ENABLED` gates everything; `get_sms_worker()
  is None` also disables enqueue.
- **Billing**: `_maybe_queue_receipt` after bill commit (own transaction,
  swallows all errors, never slows billing). `/api/sms/messages`,
  `/api/sms/status` (lowercase canonical keys: `{total,queued,sending,sent,
  failed}`), `POST .../resend` (FAILED only, else 409) — STAFF+, store-scoped.
- **Frontend**: Billing gets a Receipt SMS column (Sent/Queued/Sending/Failed
  badge from latest msg per bill, Resend on FAILED) + honest on-banner with
  sent/queued/failed counts or "not configured — set MSG91_AUTH_KEY". SMS loads
  best-effort (never breaks the Sales page).
- `docs/milestone_31_sms_bill_receipts.md` written; human must set
  `SMS_ENABLED=true` + `MSG91_AUTH_KEY`, send a real ₹ receipt, confirm SENT
  on a handset (no fabricated delivery recorded).

**M30 DONE — backend 540 passed / frontend 157 passed; gates green; hardware phase pending:**
- **Stability gate**: ByteTrack tracks need `stable_track_min_frames` consecutive
  frames (default 1; runtime/global `PERSON_STABLE_TRACK_MIN_FRAMES`; per-camera
  value >1 wins) before Re-ID / zone events / journey association — kills
  one-frame "person journeys".
- **Layer-A hot cache**: new `backend/app/edge/person_cache.py` — one store-scoped
  `PersonStateManager` per runtime (LRU+TTL, default 86400s / 2048 entries),
  keyed by opaque `(store_id, global_person_id)`; `resolve_track` before any
  expensive Re-ID; embeddings memory-only, never persisted. Track index is
  **store-scoped** (`(store_id, camera_id, track_id)`) so same cam+track ids in
  different stores never cross. Public `public_stats()` emits canonical M29
  payload keys (`size/max_entries/hits/misses/inserts/evictions_*/reid_*/
  hit_rate`); `count_reid_invocation/count_reid_skip`.
- **Selective Re-ID**: hot path reuses the cached global id with a cheap
  `associate(embedding=None)` recency touch (`reid_skip`); encode+associate runs
  only on new tracks / refresh cadence (GIM re-acquisition gap stays honored) /
  cache disagreement. Same person → same journey (no TRACK_ASSOC on refresh).
- **Data policy (corrected)**: `person_observation_persistence` defaults **True**
  (preserves M13/M14/M19 dashboards), throttled by `min_observation_gap_seconds`
  and purged after `PERSON_OBSERVATION_RETENTION_HOURS=24`; a store sets it False
  for pure cache-only mode (writer skips PERSON writes; journey events unaffected).
  `ObservationWriter.persist_person_observations` flag; `_make_writer` passes the
  PipelineConfig flag.
- **Retention**: `JourneyService.purge_analytics(store_id, retention_days=30)`
  (deletes person_track_associations → person_camera_transitions → zone_visits →
  global_person_sessions by session; never business tables) +
  `ObservationService.purge_person_observations(store_id, retention_hours=24)`
  (PERSON rows only). CLI `backend/scripts/purge_analytics.py` (dry-run default,
  `--yes` required, demo-store guard, `--store-id|--all`).
- **AI FPS pacing**: `ai_target_fps` (CameraConfig + Settings, 0=uncapped)
  paces only AI stages; bounded deque drops OLDEST frame on overflow. Worker
  `_ai_period = 1.0/ai_target_fps`.
- **Stage timings**: `StageProfiler` (bounded 300 samples; p50/p95/mean/min/max)
  in `workers.py` records pipeline_ms, pipeline.person_total_ms/reid_ms/product_ms/
  ocr_ms, write_ms (capture_ms recorded only under DEBUG logging — documented
  caveat); exposed via status `stage_profile`; `EdgeCameraStatus` schema now carries
  `ai_target_fps`, `stage_profile`, `person_cache`.
- **Frontend**: DetectionStats add AI target FPS, Re-ID runs/skips, cache hit
  rate, stage-latency row; `types.ts` adds `StageProfileSample`,
  `PersonCacheStatus`; M29 fields optional (old deployments omit them).
- **Benchmark**: `backend/scripts/benchmark_edge.py` (measured-only; file/USB;
  `--fps` pacing; prints worker status + stage profile + cache). Report:
  `docs/m29_performance_report.md` — real measured numbers on this Mac
  (uncapped ~9.78 inference fps / 57.8% drop at file rate; paced cuts AI load
  ~72%; first-call YOLO warm-up 2.1 s). Re-ID latency NOT measured (no
  `models/reid/` provider installed) — explicitly pending hardware. No
  fabrication: un-run scenarios stay "pending".
- **Tests (+21)**: `test_person_cache.py` (10; store scoping, TTL, capacity LRU,
  zone bookkeeping, reid counters, threads), `test_m29_pipeline.py` (8; stable
  gate, interrupted candidate, selective reid cadence, cached-track events,
  StageProfiler, ai_period, writer persistence off/on), 3 retention tests in
  `test_journeys.py`. Full suite **508 passed** (487 baseline), `alembic check`
  clean (config/memory-only change), frontend tsc + **153 vitest** + build green.

**M30 details (backend 540 / frontend 157):**
- **Pipeline**: `PipelineConfig.shelf_snapshot_interval_seconds` (default 30;
  **0 = disabled**) drives a WALL-CLOCK gate in `EdgePipeline` decoupled from
  the live person loop; `product_scan_interval_seconds` `0` = every frame
  (legacy, comment fixed in `config.py`). Per region: product-box geometry →
  `fill_percentage` → EMPTY(<10)/LOW(10–<35)/MEDIUM(35–<70)/FULL(≥70); a
  tracked person box overlapping the region (≥ `shelf_occlusion_overlap_fraction`
  0.15) marks the snapshot **occluded** (never real fill, never counted EMPTY).
- **Persistence**: `ShelfSnapshotService` (new, `app/services/shelf_snapshot/`)
  writes `shelf_snapshots` rows + **root-relative on-disk JPEGs** under
  `SHELF_SNAPSHOT_DIR` (retention `SHELF_SNAPSHOT_RETENTION_DAYS=7`).
  `write_snapshot` `shelf_label`/`region_bbox` optional; `store_id or ""`
  default → callers/tests MUST pass a real store_id (FK/NOT NULL). Snapshots are
  observations only — never touch inventory.
- **Layer-A mirror (user decision)**: PG stays authoritative; the worker pushes
  every written row into `backend/app/edge/shelf_snapshot_cache.py` —
  `ShelfSnapshotCache` (LRU+TTL 86400s/4096, one per runtime, key
  `(store_id,camera_id,shelf_code)`, deque maxlen `per_region_history`=24,
  canonical `public_stats()` keys). Summary/history/trend/single APIs are
  **cache-first** (`_cache_hits` requires `str(runtime.store_id)==str(store_id)`)
  with SQL fallback; the image endpoint always reads the DB (paths never
  mirrored). `EdgeCameraStatus`/`EdgeStatus` gain `shelf_snapshot_cache` stats.
- **Router**: `app/api/routers/shelf_snapshots.py` — `/summary`, `/history`,
  `/trend`, `/{id}`, `/{id}/image?prefer=crop|full` (path-traversal guard).
  `/summary` uses `func.max(ShelfSnapshot.observed_at)` for GROUP BY (raw column
  → PG GroupingError).
- **Frontend**: `ShelfMonitor.tsx` card on CameraDetail (fill bars, status
  badges, occluded warning, last-scan, status counts; refresh keyed to the live
  poll); `lib/api/shelfSnapshots.ts` + types. Honest "No shelf snapshots yet"
  empty state.
- **Tests (+32)**: `test_shelf_snapshots.py` (16; cadence/0-semantics,
  occupancy+occlusion, service+disk/traversal/retention, API+authz, **cache-first
  summary when runtime wired + DB empty**), `test_shelf_snapshot_cache.py` (11;
  put/history/scoping/LRU/TTL/trend/stats/runtime wiring), worker mirror test in
  `test_edge_ai.py`, config settings tests; `test_migrations.py` +
  `test_startup_and_system.py` updated to head `d5e8b0c2e4f6`. `alembic check`
  clean. Gates: `npx tsc -b`, **157 vitest**, `npm run build` green.

**Previous milestone summary (for reference):**
**M27 progress (backend 486 passed / frontend 149 passed):**
- **Phase 1 — audit DONE**: `docs/m27_real_world_audit.md` (12 sections,
  measured evidence, no code changes). Key measured finding: the installed
  `models/shelf/shelf_model.pt` is a 55-class FMCG model with **no biscuit
  class**; product mappings are exact-string via `Product.ai_classes`.
- **Phase 2-5 — person identity/session lifecycle DONE**: root cause was
  `GlobalIdentityManager._best_candidate` unconditionally refusing every
  same-camera match (`association.py:254`), so each ByteTrack id re-creation
  became a new global id AND a new journey. Added **guarded same-camera
  re-acquisition**: reconnect only when the person has been absent
  `REID_SAME_CAMERA_REACQUISITION_SECONDS` (2s) .. `..._MAX_GAP_SECONDS` (15s),
  no other local track is active on that camera, and appearance clears
  `REID_SAME_CAMERA_SIMILARITY_THRESHOLD` (0.85). Concurrent same-camera tracks
  are still never merged. New `ReIDConfig` fields + Settings + `.env.example`.
  Tests `test_journeys.py::test_o..u` (same track; re-acquire; disabled; weak
  appearance; long absence; concurrent reject; one journey for re-acquired id).
  Full backend **452 passed** (was 441), no regressions.
- **Phase 7-11 — product/shelf DONE (backend + UI)**: `CameraConfig.shelf_regions`
  added and forwarded by `edge_api._config_from_camera`; `schemas/camera.py`
  `_validate_shelf_regions` validates code/label/4-number bbox (x2>x1,y2>y1);
  `shelf_intelligence._shelf_lookup` made deterministic (`.order_by(Shelf.code,
  Shelf.id)`); `docs/model_capabilities.md` documents the real 55-class model and
  that unknown classes surface as `mapped=false` "Unmapped" rows. New
  `frontend/src/components/camera/ShelfRegionEditor.tsx` + 3 tests lets an
  operator define regions honestly (no shelf detector), wired into CameraDetail.
- **Phase 12-16 — mobile intake DONE**: `intake_service.photo_path`, STAFF+
  `GET /api/mobile-intake/jobs/{id}/photo` (`FileResponse`, 404 on missing),
  `photo_url` on the job schema; frontend `mobileIntake.photoBlobUrl`,
  `ReceiveSmart.tsx` now shows the phone photo, uses `capture="environment"`,
  offers Rescan on FAILED jobs, and closes the job after a confirmed receipt.
  Tests: backend `test_mobile_intake.py` photo streamed/404; frontend
  `ReceiveSmart.test.tsx` rescan + close-after-confirm.
- **Phase 17-21 — multi-camera DONE (UI + backend)**: frontend `Cameras.tsx`
  add/edit/delete camera modal (usb/file/rtsp, device index/source, active,
  person/product pipelines), per-camera Start/Stop and "Start all" calling the
  Edge runtime; honest RTSP "reserved — not yet supported" notice; card actions
  moved out of the `<Link>` to avoid nested interactives. Backend: new
  `app/edge/health.py` (`camera_health` → canonical RUNNING/STARTING/ERROR/
  STOPPED/DISABLED, included in every `EdgeCameraStatus`); `EdgeRuntime`
  capacity guardrail (`EDGE_MAX_CAMERAS`, 0=unlimited) refusing a start beyond
  capacity with a 409; and a runtime↔DB `reconcile()` supervisor that
  stops+removes workers whose DB camera is inactive/deleted (called by
  `GET /edge/cameras`, only when the runtime is store-scoped). `EdgeStatus` now
  exposes `max_cameras`; frontend `Cameras.tsx` uses the backend `health` enum.
  11 new tests (backend 8, frontend 3).
- **Phase 27-28 — demo isolation DONE**: demo activations/resets are now
  confirmation-gated in `DemoControlCenter.tsx` (declining issues no request);
  test added. Global `DemoBadge`/`DemoBanner` already label the deterministic
  demo store (M21).
- **Phase 22-26 — intelligence API sweep DONE**: new explicit
  `PRODUCT_CANDIDATE`/Unknown-product path — `ProductIntelligenceService.candidates()`
  (unmapped-only, deterministic), `ProductCandidateRead/List` schemas, STAFF+
  `GET /api/intelligence/product-candidates`; honest wording
  `UNKNOWN_PRODUCT_MESSAGE` in the service + `COMPARISON_STATUS_LABEL.NOT_ASSESSED`;
  `ProductIntelligence.tsx` stat now "Product candidates"; frontend
  `intelligenceApi.productCandidates` + `ProductCandidateRow` type.
- **Phase 34 — real-vs-demo labelling DONE**: global `DemoBadge` now renders an
  explicit emerald "Real data" chip for non-demo stores (was null) and keeps the
  amber "Demo store" link for demo; +2 tests. Second field added: shelf
  **temporal smoothing** — `_smoothed_occupancy` uses the MEDIAN of wall-clock
  60s-bucket occupancies when there are >=3 buckets (`occupancy_method`
  `median_60s`), else raw; `occupancy_samples` exposed; `ShelfIntelligence.tsx`
  shows "Smoothed over N time samples". 4 new backend tests.
- **Phase 6/17/19/20/29/31 gap-closure DONE** (final sweep against the M27 spec):
  - **Phase 6/27**: new `backend/scripts/reset_journeys.py` deletes only
    `person_track_associations → person_camera_transitions → zone_visits →
    global_person_sessions`, scoped by `--store-id`/`--all`, requires `--yes`
    (dry-run otherwise), refuses the demo store unless `--include-demo`, and
    never touches observations/inventory. Test
    `test_journeys.py::test_reset_journeys_deletes_only_target_store`.
    `DemoBanner.tsx` reset is now `window.confirm`-gated (+2 tests).
  - **Phase 17**: `Cameras.tsx` empty state has 1/2/3/4/4+ quick-start
    templates (`STARTER_CAMERAS` = Entrance/Aisle/Billing/Back Room) that create
    REAL DB rows; `+2` frontend tests.
  - **Phase 19**: per-camera `fps_cap` is now reachable —
    `CameraConfig.fps_cap`, forwarded by `edge_api._config_from_camera`,
    validated in `schemas/camera.py`, UI field + honest "0 = uncapped" hint; the
    camera form now writes the nested `config.pipelines` shape the runtime
    reads (previously wrote flat flags the runtime ignored). Capacity limit
    banner in `Cameras.tsx` when running >= `max_cameras`.
  - **Phase 20**: `health.py` adds `HEALTH_DEGRADED` (running+connected but
    stalled) + `stalled` param; `workers.py` computes it from
    `FRAME_STALL_SECONDS=10.0`. `CameraDetail.tsx` header now derives from the
    canonical `edge.health` (AI DEGRADED/CONNECTING/ERROR) instead of ad-hoc.
  - **Phase 29**: `workers.py` exposes `capture_fps`, `inference_fps`,
    `inference_ms` (EWMA), `last_frame_age_seconds`; `DetectionStats.tsx` shows
    Capture/Inference FPS + latency and "Measuring…" instead of a fake 0.
  - **Phase 31**: tests added for DEGRADED/exhaustive health states, fps_cap
    forwarding, 4-camera support + 5th refused, stop-one-doesn't-stop-others,
    deterministic NORMAL shelf, journey-scoped reset.
  - Verified: backend **470**, frontend **144**, `npx tsc -b` clean,
    `npm run build` green, `alembic check` clean (counts later grew with the
    camera-OCR and shelf-refill tests below to **486 backend / 149 frontend**).
- **Camera OCR product-label reads DONE (assistive)**: opt-in live-camera OCR
  (`config.pipelines.ocr`, `ocr_interval=30`) writes `EXPIRY_METADATA`
  observations and conservatively resolves the printed name to a catalog product.
  New `backend/app/services/product/name_matcher.py` (`ProductNameMatcher`,
  `NameMatch`, `normalize_name`, `DEFAULT_MIN_SCORE=0.86`, `MIN_ALIAS_LENGTH=4`)
  skips label noise (dates/`MRP`/`EXP`/`MFG`/`BATCH`) and refuses to guess;
  aliases = product `name` + `brand` + `ai_classes`; ties break by name then id.
  `ObservationWriter._match_ocr_product` + `_load_name_matcher` attach
  `product_id` and `details` (`recognized_product_name`, `label_match_score`,
  `matched_label`, `catalog_price`); `record_expiry_metadata_observation` gained
  `product_id`/`details_extra`. `EdgeRuntime.add_camera` disables the OCR tap
  (and flips `pipelines.ocr` false) if PaddleOCR weights fail to load — a missing
  model never stops the camera. Frontend: `Cameras.tsx` OCR toggle (nested
  `pipelines.ocr`) + `ProductLabelReads.tsx` panel in `CameraDetail.tsx`
  (matched / unrecognized / empty states). Never mutates inventory. Tests:
  `test_name_matcher.py` (9), `test_observations.py` (2),
  `test_edge_ai.py::test_runtime_survives_unavailable_ocr_model`,
  `ProductLabelReads.test.tsx` (3), `Cameras.test.tsx` OCR persistence. Docs:
  new `docs/camera_ocr_product_labels.md`, updated `docs/model_capabilities.md`.
- **Shelf fill analysis + refill alerts DONE**: `shelf_intelligence.py`
  `LOW_OCCUPANCY_FRACTION` 0.35 → **0.5** (LOW_VISIBLE = "half full or less", uses
  `<=`) and new `ShelfIntelligenceRow.refill_recommended` (True for EMPTY/LOW,
  never UNKNOWN) exposed in `ShelfIntelligenceRead` + frontend type; empty/low
  `last_analysis_message` says "refill ASAP"/"refill". New alert type
  `ALERT_SHELF_EMPTY` (`SHELF_EMPTY`, model+exports) → CRITICAL "Shelf {code} is
  empty — refill now" (`recommended_action: refill_now`); `LOW_SHELF_OCCUPANCY`
  reframed as "about to get empty — refill soon" (`recommended_action:
  refill_soon`; severity HIGH if pct<15 else MEDIUM). `AlertRuleEngine.
  _evaluate_shelf_fill` replaced `_evaluate_low_shelf_occupancy`, wrapped by new
  public `evaluate_shelf_fill(trigger=...)`; `POST /api/reconciliation/run` now
  calls it after results (`trigger="reconciliation"`, best-effort) so refill
  alerts are a reconciliation outcome — alerts only, never stock. Frontend:
  `alerts.ts`/`types.ts` add `SHELF_EMPTY`, `ShelfIntelligence.tsx` includes
  `SHELF_EMPTY` in related alerts, "Half full or less"/"Refill now/soon"
  messaging. Tests +4 backend / +1 frontend: `test_intelligence.py::
  test_shelf_half_full_recommends_refill`, `test_alerts.py::
  test_shelf_empty_alert_refill_now`, `..._shelf_fill_alerts_after_reconciliation`,
  `test_api_reconciliation_run_triggers_shelf_fill_alerts`,
  `ShelfIntelligence.test.tsx` refill recommendation. Docs:
  `docs/milestone_16_alerts.md` + `docs/milestone_15_product_shelf_intelligence.md`.
- **Remaining**: Phase 32 physical-camera verification still needs a human
  (one-person/30s, two-people, product, shelf, mobile USB, multi-camera). No
  hardware available to the agent. All code/docs phases complete.

**Camera pipeline fix DONE — backend 441 passed / frontend 127 passed; all gates green:**
- **Root cause (UI zeros)**: `frontend/src/pages/CameraDetail.tsx` loaded data
  once on mount and never polled, so stat panels were a stale pre-detection
  snapshot while the MJPEG stream stayed live. Fixed with
  `LIVE_REFRESH_MS = 2000`, `refreshLive()` (observations + summary + edge
  status only; heavy intelligence/reconciliation/alerts stay on initial load),
  a `setInterval` cleared on unmount, and an immediate refresh on start/stop.
- **Secondary defect (fixed)**: `CameraWorker._write_events` closed its
  `ObservationWriter` every frame, resetting the per-kind throttle
  (`min_observation_gap_seconds`) → PERSON rows written ~7/s instead of ~0.5/s.
  Now one persistent writer per worker; `_close_writer()` closes it on `stop()`
  or after a write failure; injected test writers are never closed
  (`_writer_owned` guard). Added throttled DEBUG diagnostics in `_process_one`
  (every 30th frame: frame#, infer ms, event/person/product counts, track ids,
  written total; no images).
- **Evidence**: `observations` held 1605 rows for the camera (1557 PERSON, 48
  PRODUCT, 7 tracks); API list/summary returned the same; edge status
  `observations_written: 1621`; log showed a clean `stop()` (not a crash).
- **Tests**: `backend/tests/test_edge_ai.py::test_worker_reuses_writer_across_frames_and_closes_on_stop`;
  `frontend/src/pages/CameraDetail.test.tsx::polls live so newly-detected
  observations appear without a manual refresh`. Full suite **441 backend / 127
  frontend**; `npx tsc -b` clean; `npm run build` green (110.31 kB gzip JS);
  `alembic check` clean (no schema change needed).
- **Docs**: new `docs/debug_camera_observation_pipeline.md` (12 sections:
  symptom, constraints, pipeline map, reproduction, evidence, root cause,
  secondary defect, fix, verification, intentionally-unchanged, prevention,
  files touched).

**Prior Auth milestone DONE (reference) — as recorded in `docs/authentication.md`:**
- **Backend**: `app/core/auth.py` (Argon2id + roles/aliases), `app/models/auth_session.py`
  (`sessions` table, SHA-256 token hash only), `app/services/auth_service.py`
  (create/resolve/revoke session, login, change-password, in-memory throttle),
  `app/api/deps.py` (`get_current_user`, `require_role`, `require_csrf`),
  `app/api/authz.py` (`require_same_store`→403, `effective_store_id`,
  `scoped_get`→404 incl. Store-by-`id`), `app/api/routers/auth.py`
  (`/api/auth/login|logout|me|change-password|logout-all`), `users.py`
  (OWNER-only provisioning).
- **All business routers** wired with auth + store scope: `cameras`, `zones`,
  `shelves`, `products`, `customers`, `sales`, `bills`, `notifications`,
  `alerts`, `observations`, `reconciliation`, `intelligence`, `batch_intake`,
  `journeys`, `insights`, `mobile_intake`, `inventory`, `stores` (OWNER
  lifecycle; `GET /api/stores` returns own store only), `app/api/edge_api.py`.
- **Role policy**: reads STAFF+ everywhere; cameras/zones/shelves/products/
  notifications MANAGER+; customers/sales/bills STAFF+; inventory receive +
  movements + batch_intake scan/confirm STAFF+, inventory adjust/reorder/batches
  MANAGER+; alerts & insights mutations + reconciliation run MANAGER+;
  mobile_intake status/jobs/get/close/rescan STAFF+ (demo-queue keeps reset-key
  guard); edge status/cameras/stream STAFF+, start/stop MANAGER+; users/stores
  OWNER.
- **Migration**: `backend/alembic/versions/f4a9c0a1b2c3_add_authentication_fields_and_sessions_tab.py`;
  **new head = `f4a9c0a1b2c3`** (was `19c835a1a344`). `alembic check` clean.
- **Seeds**: `seed_demo.py` → `demo@storeye.local` / `StoreyeDemo@123` (OWNER,
  idempotent, real hash); `seed.py` → `owner@storeye.local` / `StoreyeOwner@123`
  (OWNER bootstrap). `requirements.txt` adds `argon2-cffi>=23.1,<24.0`.
  `.env.example` has an AUTHENTICATION section.
- **Tests**: new `backend/tests/test_authentication.py` (24 pg). Existing HTTP
  modules retrofitted via `tests/conftest.py` helpers (`FakeUser`, `make_store`,
  `bind_test_user`, `unbind_test_user`). `test_migrations.py` head/table
  updated. Full suite grew to **440** (was 378) at auth delivery; now **441**
  after the camera-pipeline writer regression test.
- **Frontend**: `lib/api/client.ts` now uses `credentials: 'include'` + CSRF
  header, no bearer/localStorage; new `lib/api/auth.ts`; `auth/AuthContext.tsx`
  rewritten (real login/logout/logout-all/change-password + `me` restore +
  `isLoading`); `auth/ProtectedRoute.tsx` waits for restore; `pages/Login.tsx`
  email+password; `pages/Settings.tsx` account + change-password + sign-out-all;
  `config/demo.ts` no longer holds the demo password; `frontend/.env.example`
  drops `VITE_DEMO_PASSWORD`. Gates: `npx tsc -b` clean, **125 vitest passed**
  at auth delivery (now **127**), `npm run build` green.
- **Docs**: new `docs/authentication.md`; README + `.env.example` updated.

**M28 — Shopkeeper-first frontend redesign + footfall graph DONE (all gates green:**
**backend 487 passed / frontend 153 passed / tsc clean / build green / alembic check clean):**
- **Backend (small read-only addition, §38)**: `GET /api/journeys/daily?store_id=&days=`
  (default 3 av 7, ge=1 le=30) → `{items:[{date, visitors}]}` — one row per
  `GlobalPersonSession` counted on UTC day of `first_seen_at`, zero-filled oldest→newest,
  store-isolated. `DailyFootfallRead`/`DailyFootfallListRead` (exported via
  `app/schemas/__init__.py` incl. `__all__`), `JourneyService.daily_visitors`,
  route defined BEFORE `/{global_person_id}`. Tests: `test_journeys.py::test_v_daily_footfall_buckets_sessions_by_utc_day`
  + daily route assertions in `test_journeys_api.py`.
- **Frontend IA (§3–§6, §44)**: `AppShell.tsx` rewritten — WORKSPACE nav (Home
  /app, Sales /app/sales, Stock /app/stock, Receive Stock /app/receive, Alerts,
  Reports) + STORE OPERATIONS (Cameras, Settings) + **Demo item only when
  `isDemo`**; mobile bottom bar = Home/Sales/Stock/Receive/Alerts + More→Settings;
  search bell decluttered away; header store name + status pill ("Store running
  locally"/"Offline mode"). Old routes kept; new aliases added in `App.tsx`:
  `/app/sales`, `/app/stock`, `/app/receive`, `/app/dashboard`, `/app/settings/advanced`.
- **Advanced hub (§4, §43)**: new `SettingsAdvanced.tsx` page (canManage-gated)
  links to Stock activity, Shelf configuration, Product intelligence, AI
  diagnostics, Observations, Stock check, Customer journeys, AI insights, Live
  store view; `Settings.tsx` gains store-tool tiles (Products, Customers,
  Cameras, Live store) + Advanced + Demo (isDemo) tiles.
- **Home/Dashboard rewritten (§7–§8)**: greeting + store/status header; KPI cards
  (Today's Sales ₹ via `formatINR` string — **avoid `Stat`/rAF in jsdom**,
  Current Stock units, Running Low, Expiring Soon, Today's Bills); "What needs
  your attention" from **real data only** (out-of-stock/running-low/expired/
  expiring via inventory+batches, pending mobile-intake receipts, offline edge
  cameras, shelves needing restock) → green "Nothing needs your attention right
  now." when clear; Quick Actions (Receive Stock/New Sale/Check Stock/View
  Alerts); 7-day Sales line chart + **7-day footfall BarChart from
  `journeyApi.daily`**; Store activity (customers today = journeys 24h summary,
  products seen, shelves needing restock); Cameras card; Recent receipts.
- **Translation layer (§35, §40)**: new `frontend/src/lib/shop.ts` (`greeting`,
  `formatINR`, `stockStatus` GOOD/LOW/OUT, `expiryLabel`, `alertCategory`,
  `alertTypeLabel`, `ALERT_SEVERITY_LABEL`, `EMPTY_COPY`, `ERROR_COPY`,
  `errorMessage`). `AlertSeverityBadge` now renders `ALERT_SEVERITY_LABEL` (e.g.
  "Urgent") instead of leaking `CRITICAL` in the normal UI; `AlertCard` uses
  `alertTypeLabel`.
- **Page wordings**: Billing → **Sales** (KPI row + "+ New Sale" + Recent bills,
  "View customers →" link); Inventory → **Stock** (filters All/Running low/
  Out of stock/Expiring soon via `stockStatus`+`expiryLabel`, Status + Expiry
  columns, "+ Receive Stock", "Manage products →"); ReceiveSmart → **Receive
  Stock** ("Scan with your phone", "← Stock" back-link); Alerts → "Things that
  need attention" ("Check now" button); Cameras → "Your cameras" + "Set up your
  first camera" + Live-store link.
- **Frontend tests §47**: `Dashboard.test.tsx` rewritten (real-API KPIs,
  footfall-empty/attention-empty states, out-of-stock attention item, offline
  mode); new `AppShell.test.tsx` 4 tests (shopkeeper nav, no AI pages leakage,
  Demo only when demo store, mobile bottom bar + More→Settings); updated
  `Alerts/Inventory/ReceiveSmart/Billing/Cameras/DemoPresentation` tests in step
  with the new copy. **Gotcha**: `getByRole('link', {name})` name matching is
  substring-free exact — use exact strings ("Stock" vs "Receive Stock"); unused
  JS `alertRes`/`busyCount`/`shelfNames`/`mostVisited` dead code removed from
  Dashboard.
- **Intentionally NOT done (§38)**: no backend business-logic rewrite; no
  feature/route deletion (advanced pages live under Settings→Advanced, old
  routes still resolve); no fabricated dashboard numbers (all real APIs,
  best-effort, each metric independently try/catch); footfall semantics
  documented in `docs/milestone_15_product_shelf_intelligence.md`? no — kept in
  code comments + `docs/` below pending final report (see Next Move).

## Important Notes
- **DB URLs**: `DATABASE_URL="postgresql+psycopg2://storeye@localhost:5433/storeye"` for alembic/seed/integrity CLI; tests use `TEST_DATABASE_URL` → `storeye_test`. Run pytest from `backend/` with `.venv/bin/pytest`.
- **Auth test pattern**: domain HTTP tests bind a fake authenticated user via `bind_test_user(store_id, role="OWNER")` (overrides `get_current_user`), which keeps `require_role`/`authz` live. `client` fixtures clear `app.dependency_overrides` at teardown. `test_authentication.py` drives the real cookie flow against `storeye_test`.
- **Cross-store semantics changed**: a store the caller does not own is **403** for a `store_id` param/payload and **404** for a scoped row (`scoped_get`). Old tests expecting 404 for unknown-store params were updated to 403.
- **`scoped_get` Store special-case**: `Store` has no `store_id` column, so scoping falls back to comparing the row's `id`. Don't "fix" it back.
- **CSRF**: only auth mutations require `X-Storeye-CSRF: 1`; the frontend client adds it on all non-GET requests. Login throttle is in-process (`AUTH_LOGIN_MAX_ATTEMPTS=8`, `AUTH_LOGIN_THROTTLE_SECONDS=900`) and is process-global in tests → `test_authentication.py` clears `auth_service._failures` per test.
- **init_engine gotcha**: `app/db/session.py:43` is a once-guarded singleton — first caller in a pytest session wins. Edge tests must `dispose_engine()` + `init_engine(TEST_DB_URL)` in their `client` fixture.
- **Shelf clock gotcha**: M15 shelf intelligence bounds its window with wall-clock `datetime.now()`; scenario/test clocks must be near wall clock.
- **Frontend gotchas**: `Stat` counts up via rAF (never advances in jsdom); `stubFetchRoutes` matches URL substrings in insertion order (list `/api/auth/logout-all` before `/api/auth/logout`, `/activate` before others); `getByText` is exact (use regex); `Button` forwards `aria-label` only; `ErrorBoundary` swallows child errors (restore `console.error` spy). AuthProvider calls `GET /api/auth/me` on mount in every test that renders it.
- **Camera pipeline gotchas**: observations live in the `observations` table (NOT `ai_observations`); `CameraWorker` must keep one `ObservationWriter` per worker across frames (resetting it resets the throttle → row flood) and close it on `stop()`/write failure; `EdgeEvent.payload` is an object (use `getattr(..., "track_id")`), not a dict; `EdgePipeline.process()` returns `(events, None)` and the worker annotates the frame itself. `CameraDetail` is the only camera page that needs ~2s live polling. Edge status keeps `started_at`/uptime after `stop()` and sets `last_frame_at=None`. Camera health is one canonical enum from `app/edge/health.py` (never re-derive it ad hoc); starting beyond `EDGE_MAX_CAMERAS` raises `CameraCapacityError` → HTTP 409; `EdgeRuntime.reconcile()` (via `GET /edge/cameras`) only runs when `runtime.store_id` equals the caller's store, so don't "fix" it to always reconcile. `Reports.test.tsx` KPI assertions must be `findBy*` (data loads after the heading) — it was flaky.
- **M29 gotchas**: `person_observation_persistence` defaults **True** (M13/M14/M19 panels) — only set it False for cache-only mode; the writer SKIPS PERSON rows but never journey events. Person cache track index is store-scoped `(store_id, camera_id, track_id)`; max-track never reuse across stores. `public_stats()` (not `stats()`) is the canonical API payload (`size/hits/misses/...`); `stats()` is diagnostics-only. `ai_target_fps` paces ONLY AI stages (capture untouched); bounded deque drops OLDEST. Persistence is config/memory-only → no migration, `alembic check` stays clean.
- **M30 gotchas**: snapshot cadence is wall-clock/deterministic (pipeline tests freeze `now`); `product_scan_interval_seconds=0` = every frame (NOT disabled) while `shelf_snapshot_interval_seconds=0` = disabled. Occluded rows are counted as OCCLUDED, never EMPTY, in summary status counts. `ShelfSnapshotService(store_id=None)` normalizes to `""` → worker/callers MUST pass a real store_id or FK/NOT NULL blows up. `write_snapshot` `shelf_label`/`region_bbox` are optional; camera_id must reference an existing camera row. Cache-first `_cache_hits` only serves when `runtime.store_id == requested store` (set the runtime store before asserting cache-vs-DB reads); image endpoints and `get_by_id` always stay DB-guarded. `/summary` GROUP BY must use `func.max(...)` (raw column → GroupingError). `ShelfSnapshotCache` `to_read_dict()` never mirrors image paths; `entry.id` is a string, row.id is a UUID.
- **M32 gotchas**: `EdgeRuntime.add_camera` now calls
  `registry.new_product_detector(...)` (NOT `get_product_detector`), so any test
  `FakeRegistry` must implement `new_product_detector` or the product tap
  silently disables (person still runs) → a persistence test can see 0 rows.
  `WorldProductDetector.set_prompts` mutates the model, so the registry caches
  world models by `(path, tuple(prompts))` — different prompts = different
  instance, identical prompts share one. Empty prompts (and empty catalog) = a
  concrete no-op; never fall back to a hidden class list. `bbox_norm` is
  `[x1,y1,x2,y2]` 0..1 **clamped** (`_normalize_box`), while demo/legacy
  obs `bbox` is `(x,y,w,h)` 0..100 — `DetectionOverlay` prefers `bbox_norm`.
  CLIP `ViT-B-32.pt` lives at `backend/weights/clip/` (gitignored, ~338 MB,
  downloaded once by Ultralytics on first `set_classes`); `yolov8s-worldv2.pt`
  is local at `models/shelf/`. Both detectors are pure CV services — no DB.
- **M31 gotchas**: `SmsOutboxService.status()` returns **lowercase** canonical keys (`queued/sending/sent/failed`) because `SmsStatusCounts(**status)` would reject uppercase schema keys. `bill_id` on sms_messages is SET NULL — deleting a bill/reset must never cascade to SMS history. Enqueue happens AFTER bill commit in its own transaction and swallows all errors — `_maybe_queue_receipt` skips when `SMS_ENABLED` false, worker is None, no customer, or mobile missing; never let enqueue raise into `create_bill`. `resend` raises `ValueError` for non-FAILED → 409. MSG91 acks on `type:success` substring (not status code); missing auth key is terminal (not retryable). Frontend: the Billing SMS banner must keep counts as flat text (nested `<span>`s break `getByText(/sent 1/i)` — getNodeText ignores child elements).
- **M23 gotchas**: doctor uses `session.execute(select(Camera)).scalars().all()`; model validator min 64 KiB and never auto-downloads; scripts run under `set -euo pipefail` → `port_pid ... || true`; `pyzbar` needs `find_library` bootstrap (works via `barcode_decoder.py`).
- Test markers: `pg`, `no_db`, `real_ai`. Camera `config.kind` must be `usb`/`file`/`rtsp`. EdgeRuntime tests use `reid_enabled=False`.
- Legacy SQLite stack (`app/core/database.py`) is diagnostics-only; `DATABASE_URL` rejects `sqlite://`.
- Main `frontend/` gates: `npx tsc -b && npx vitest run && npm run build`. `storeye-frontend/` is separate, NOT in git.
- Git: origin `https://github.com/ayushjha-creates/Storeye.git`, branch `main`. `git` may still fail with `.git/index: unable to map index file` (iCloud Drive); no auth commit has been made yet.

## Next Move
- M32 product & shelf detection DONE — backend **587**/587, frontend **164**/164,
  `npx tsc -b`, `npm run build`, `alembic check` all green; report written to
  `docs/milestone_32_product_shelf_detection.md`. Remaining: **physical-camera
  phase** — point a USB camera at a shelf with a few known products, add prompts
  (or a catalog), start the camera, confirm product boxes render in the right
  place and `ShelfMonitor` occupancy changes. No fabricated detections/perf.
  `backend/weights/clip/ViT-B-32.pt` is needed (downloaded once, gitignored);
  `models/shelf/yolov8s-worldv2.pt` is local.
- M31 SMS receipts DONE — backend **568**/568, frontend **160**/160, `npx
  tsc -b`, `npm run build`, `alembic check` all green; report written to
  `docs/milestone_31_sms_bill_receipts.md`. Remaining: **live-send** — a human
  sets `SMS_ENABLED=true` + `MSG91_AUTH_KEY` in `backend/.env`, sends a real ₹
  receipt via Sales → bill for a customer with a phone, and confirms the badge
  flips SENT with actual delivery on the handset. Also verify retry/backoff
  against a genuinely flaky network at the store.
- M30 code+tests+report DONE (backend **540**/540, frontend **157**/157, `npx
  tsc -b`, `npm run build`, `alembic check` green; report written to
  `docs/milestone_30_shelf_occupancy_monitoring.md`). Remaining: **hardware
  phase** — run the physical-camera scenarios and capture the real numbers with
  `./.venv/bin/python -m scripts.benchmark_edge [--fps N | --cam 0]` (one
  person 30 s, two people, leave-and-return, product, shelf + occlusion gate,
  mobile USB, multi-camera). Also verify Re-ID latency once a `models/reid/`
  provider is installed and confirm `capture_ms` profiler gating (currently
  DEBUG-only).
- M29 report in `docs/m29_performance_report.md`; M28/M27 written-up earlier
  (see `docs/`); nothing left besides the human-with-hardware verification
  Phase 32.
- Optional: retry `git add/commit` once the `.git/index` iCloud timeout clears
  (no commit exists yet).
