# M27 Final Report — Real-World AI Reliability & Multi-Camera System

Status: **all code/doc phases complete and verified**; Phase 32
(physical-camera acceptance) remains human/hardware-gated.

Verified gates at delivery:

- Backend: `470 passed` (`TEST_DATABASE_URL=...storeye_test .venv/bin/pytest -q`)
- Frontend: `144 passed` (`npx vitest run`)
- `npx tsc -b` clean, `npm run build` green (114.63 kB gzip JS)
- `alembic check` → "No new upgrade operations detected" (no schema change)

Hard constraints honoured throughout: no fabricated detections/counters, no
cloud AI, no face recognition/biometrics, offline-first, local PostgreSQL
authoritative, no frontend-side inference, demo mode deterministic and clearly
separated, and documented real model limits.

---

## 1. Root cause — one person counted as ~57 journeys

**Symptom.** A single physical person walking past one camera produced dozens of
"journeys" (measured session: ~57 for one person).

**Root cause.** `GlobalIdentityManager._best_candidate`
(`backend/app/services/journeys/reid/association.py:254`) unconditionally
refused every same-camera candidate. ByteTrack re-creates a local track id
whenever it loses and re-acquires the same person (occlusion, a few skipped
frames). Each re-created local id therefore became a **new global identity and a
new journey** — so N local ids for one person = N journeys.

**Fix — guarded same-camera re-acquisition.** A local track may reconnect to an
existing same-camera global identity only when **all** hold:

- the person has been absent between
  `REID_SAME_CAMERA_REACQUISITION_SECONDS` (2s) and
  `REID_SAME_CAMERA_MAX_GAP_SECONDS` (15s);
- no other local track is concurrently active on that camera;
- appearance clears `REID_SAME_CAMERA_SIMILARITY_THRESHOLD` (0.85).

Concurrent same-camera tracks are **never** merged. Files:
`app/services/journeys/reid/{config,association}.py`, `app/core/config.py`,
`.env.example`.

**Before → after.**

| | Before | After |
|---|---|---|
| One person, transient track loss | new global id + new journey per re-creation (~57) | one journey, re-acquired |
| Two people concurrently, same camera | two journeys | two journeys (still never merged) |
| Appearance below threshold | (n/a) | stays separate (no false merge) |
| Absence beyond max gap | new journey | new journey (stale) |

Tests: `backend/tests/test_journeys.py::test_o…u` (same track; re-acquire;
disabled; weak appearance; long absence; concurrent reject; one journey for a
re-acquired id), plus `test_k_track_id_collision_across_cameras` (explicit
track-id persistence).

---

## 2. Tracker / Re-ID lifecycle fixes

- ByteTrack remains the tracker; it is **not** removed or replaced.
- One long-lived tracker + Re-ID manager per camera, store-scoped.
- Global identities are created only from tracked boxes (`track_id >= 0`);
  untracked boxes are dropped (`person_detector.py:46-48`).
- Embeddings are computed in-memory and **never persisted** (no embedding
  columns); only non-biometric session metadata is stored.
- Journey reset tooling: `backend/scripts/reset_journeys.py` deletes only
  `person_track_associations → person_camera_transitions → zone_visits →
  global_person_sessions`, scoped by `--store-id`/`--all`, requires `--yes`
  (dry-run otherwise), refuses the demo store unless `--include-demo`, and never
  touches observations or inventory.
  Test: `test_reset_journeys_deletes_only_target_store`.

---

## 3. Model capability report (honest)

`docs/model_capabilities.md` is the authoritative reference.

- Person: `models/yolo/yolo11n.pt` (COCO-80, person class 0) + ByteTrack.
- Products/shelf contents: `models/shelf/shelf_model.pt` — a **55-class FMCG
  detection model**. It has **no biscuit class** and no Parle/Britannia classes.
- Product→catalog mapping is **exact string** via `Product.ai_classes`;
  unknown classes surface as `mapped=false` "Unknown product — map to catalog",
  never guessed.

### Biscuit / product not detected

Not a bug in the pipeline: the installed shelf model simply does not contain a
biscuit class. What was added to make this honest and actionable:

- `ProductIntelligenceService.candidates()` (unmapped-only, deterministic),
  `ProductCandidateRead/List`, STAFF+
  `GET /api/intelligence/product-candidates`.
- `UNKNOWN_PRODUCT_MESSAGE` + `COMPARISON_STATUS_LABEL.NOT_ASSESSED`
  ("Unknown product — map to catalog").
- `ProductIntelligence.tsx` "Product candidates" stat.

To detect biscuits, an operator must map an existing model class to the product
(`Product.ai_classes`) or supply a model that actually contains it.

### Shelf intelligence

There is **no shelf-detection model**. A "shelf" is an operator-configured
region in `camera.config.shelf_regions` (`code`, `label`, pixel-space
`[x1,y1,x2,y2]`). Intelligence = spatial association of detected products +
estimated visible occupancy. Added:

- `schemas/camera.py::_validate_shelf_regions` (code/label/4-number bbox,
  `x2>x1`, `y2>y1`), forwarded by `edge_api._config_from_camera`.
- Deterministic `_shelf_lookup` (`.order_by(Shelf.code, Shelf.id)`).
- Temporal smoothing: `_smoothed_occupancy` uses the **median** of wall-clock
  60s-bucket occupancies when `>=3` buckets (`occupancy_method="median_60s"`),
  else `raw`; `occupancy_samples` is exposed; UI shows "Smoothed over N time
  samples".
- UI `frontend/src/components/camera/ShelfRegionEditor.tsx` lets an operator
  define regions honestly, wired into `CameraDetail.tsx`.

---

## 4. Mobile USB intake

- `intake_service.photo_path`; STAFF+ `GET /api/mobile-intake/jobs/{id}/photo`
  (`FileResponse`, 404 on missing); `photo_url` on the job schema.
- Frontend `mobileIntake.photoBlobUrl`; `ReceiveSmart.tsx` shows the phone photo,
  uses `capture="environment"`, offers Rescan on FAILED jobs, and closes the
  job after a confirmed receipt.
- Tests: backend photo streamed/404; frontend rescan + close-after-confirm.

---

## 5. Multi-camera (1 / 2 / 3 / 4+ / N)

- Backend `app/edge/health.py` is the single canonical health enum:
  `RUNNING`, `DEGRADED`, `STARTING`, `ERROR`, `STOPPED`, `DISABLED`.
  `DEGRADED` = running+connected but stalled (`FRAME_STALL_SECONDS=10.0` in
  `workers.py`). Included on every `EdgeCameraStatus`.
- `EdgeRuntime` capacity guardrail: `EDGE_MAX_CAMERAS` (0 = unlimited);
  starting beyond capacity raises `CameraCapacityError` → HTTP 409.
- `EdgeRuntime.reconcile()` (called by `GET /edge/cameras` only when the runtime
  is store-scoped) stops+removes workers whose DB camera is inactive/deleted.
- `EdgeStatus.max_cameras` exposed.
- `Cameras.tsx`: add/edit/delete modal (usb/file/rtsp), per-camera Start/Stop,
  "Start all", RTSP "reserved — not yet supported" notice, capacity-limited
  banner when running `>= max_cameras`, and 1/2/3/4/4+ quick-start templates
  (`STARTER_CAMERAS` = Entrance/Aisle/Billing/Back Room) that create **real DB
  rows**.
- Per-camera `fps_cap` reachable: `CameraConfig.fps_cap` → `_config_from_camera`
  → `EdgeRuntime` → `CameraWorker`; validated in `schemas/camera.py`; UI field
  with "0 = uncapped" hint. The camera form now writes the nested
  `config.pipelines` shape the runtime reads (previously flat flags the runtime
  ignored).

Tests: 4-camera support + 5th refused; stop-one-doesn't-stop-others; fps_cap
forwarding; exhaustive/DEGRADED health; deterministic NORMAL shelf.

No camera-count limit exists in the Camera model; the practical ceiling is the
edge machine's CPU/memory and `EDGE_MAX_CAMERAS`.

---

## 6. FPS / latency measurement

`CameraWorker` exposes measured (never fabricated) values:

- `capture_fps` = `frames_captured / elapsed`
- `inference_fps` = processed frames / elapsed
- `inference_ms` = EWMA of per-frame inference time (0.2/0.8)
- `last_frame_age_seconds`

`DetectionStats.tsx` shows Capture FPS / Inference FPS / Inference latency and
"Measuring…" instead of a fake 0 when no frames have flowed yet.

---

## 7. Demo isolation & real-vs-demo labelling

- Demo activations/resets are confirmation-gated in `DemoControlCenter.tsx`;
  `DemoBanner.tsx` reset is `window.confirm`-gated; declining issues no request.
- Global `DemoBadge` renders an emerald "Real data" chip for non-demo stores and
  the amber "Demo store" link for the deterministic demo store.
- Demo data never mixes with production data; the demo store is labelled on
  every page.

---

## 8. Database verification

- Observations live in the `observations` table (not `ai_observations`).
- `CameraWorker` keeps one `ObservationWriter` per worker across frames
  (resetting it per-frame reset the per-kind throttle and flooded PERSON rows);
  it is closed on `stop()`/write failure. Regression test:
  `test_edge_ai.py::test_worker_reuses_writer_across_frames_and_closes_on_stop`.
- `alembic check` is clean: no new migration was needed for M27.
- Auth milestone (reference): head `f4a9c0a1b2c3`.

---

## 9. Tests added this milestone (highlights)

Backend: same-camera re-acquisition (`test_o…u`), journey-scoped reset,
product-candidates, shelf smoothing (+4), DEGRADED/exhaustive health, fps_cap
forwarding, 4/5-camera capacity, stop-isolation, deterministic NORMAL shelf.

Frontend: shelf-region editor (+3), DemoBadge real-data chip (+2), DemoBanner
confirm (+2), 1-camera template quick-start, capacity banner, CameraDetail live
polling, DetectionStats measured FPS/latency.

---

## 10. Physical acceptance — Phase 32 (PENDING HUMAN)

No hardware is available to the agent, so the following MUST be run by a human
and cannot be claimed as verified:

1. One person in front of one camera for ~30s → **1 journey** (not tens).
2. Two people at once → **2 journeys**, no cross-merge.
3. Product held to camera → detected/mapped when the class exists, otherwise an
   honest "Unknown product" candidate.
4. Shelf region with product → NORMAL/LOW occupancy from configured regions.
5. Phone capture over USB/hand-off → job shows the real image; confirm closes it.
6. 1, 2, 3, 4, and 4+ cameras → independent start/stop; capacity limit enforced.

Run commands:

```bash
# backend
cd backend
TEST_DATABASE_URL="postgresql+psycopg2://storeye@localhost:5433/storeye_test" .venv/bin/pytest -q
DATABASE_URL="postgresql+psycopg2://storeye@localhost:5433/storeye" .venv/bin/alembic check

# frontend
cd frontend
npx tsc -b && npx vitest run && npm run build
```

---

## 11. Known limitations (unabridged)

- The shelf model has no biscuit class; biscuit detection requires mapping an
  existing class or a new model.
- No shelf-detection model — regions are operator-configured.
- RTSP capture is reserved and reports an explicit error rather than a fake feed.
- Browser-camera intake mode is not implemented (USB/file upload is).
- Journey/Re-ID is not biometric: appearance matching is thresholded and can
  still split/merge under heavy occlusion; embeddings are never persisted.
- FPS/latency are per-process measurements and depend on the edge machine.

---

## 12. Files touched (summary)

Backend: `app/services/journeys/reid/{config,association}.py`,
`app/core/config.py`, `app/edge/{config,health,workers,runtime}.py`,
`app/api/{edge_api,edge_schemas}.py`, `app/schemas/{camera,intelligence,__init__}.py`,
`app/services/intelligence/{product_intelligence,shelf_intelligence}.py`,
`app/api/routers/intelligence.py`,
`app/services/mobile_intake/intake_service.py`,
`app/api/routers/mobile_intake.py`, `scripts/reset_journeys.py`.

Frontend: `pages/{Cameras,CameraDetail,ProductIntelligence,ShelfIntelligence,ReceiveSmart,DemoControlCenter}.tsx`,
`components/camera/{ShelfRegionEditor,DetectionStats}.tsx`,
`components/demo/{DemoBadge,DemoBanner}.tsx`,
`lib/api/{types,intelligence}.ts`.

Docs: `docs/m27_real_world_audit.md`, `docs/model_capabilities.md`,
`docs/m27_final_report.md`, `AGENTS.md`.
