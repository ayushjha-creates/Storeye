# Milestone 25 — Mobile-to-Edge USB Intake Bridge

> Completed: 2026-09-17 · Base: HEAD `19c835a1a344` (M23 state, no M24 in this
> line) · Status: **Implemented and verified** (physical USB hand-off NOT
> VERIFIED — see §9).

---

## 0. Checklist — all tasks complete

| # | Task | Where | Status |
|---|------|-------|--------|
| 1 | Recon: M17 receiving pipeline, config, demo infra, frontend Smart Receiving, deps | M17 docs (`milestone_17_smart_batch_receiving.md`), `docs/mobile_usb_intake.md` §"Why not CCTV OCR" | ✅ |
| 2 | Backend `mobile_intake` service (watcher, stability, validation, idempotency, status, errors) | `app/services/mobile_intake/{intake_watcher,file_stability,validation,intake_models,intake_service,manager,errors,demo_image}.py` | ✅ |
| 3 | Wire intake pipeline into existing M17 endpoints (no duplicates) | `manager._default_scanner` → `BatchIntakeService.scan_package`; confirm stays `POST /api/batch-intake/confirm` | ✅ |
| 4 | Intake settings in Settings/config + `.env.example` | `app/core/config.py` (`INTAKE_*`), root `.env.example` M25 group | ✅ |
| 5 | Mobile-intake API (status/jobs/one-by-id/close/rescan/demo-queue) | `app/api/routers/mobile_intake.py`, `app/schemas/mobile_intake.py`, wired in `app/main.py` + `app/api/errors.py` | ✅ |
| 6 | Frontend Mobile Intake section in Smart Receiving + demo scenario `MOBILE_USB_RECEIVING` | `frontend/src/pages/ReceiveSmart.tsx` card; `frontend/src/lib/api/mobileIntake.ts` + types; demo scenario in `demo_data.py`/`demo_scenarios.py`; picker for catalogue packs | ✅ |
| 7 | Demo mode integration + reset safety | `api/routers/demo.py` activation hook + `_require_demo_mode/_require_reset_key`; `demo_reset.py` `_reset_mobile_intake_demo_state()`; demo-only files start `storeye-demo-` | ✅ |
| 8 | Tests: watcher/stability/duplicate/invalid/barcode/ocr/expiry/review/confirm/cleanup + real E2E | `tests/test_mobile_intake.py` (36), `tests/test_mobile_intake_real_ai.py` (1 real zbar+PaddleOCR E2E, both catalogue packs) | ✅ |
| 9 | Full regression + live smoke (real local image) | 415 backend / 121 frontend green; live file-level hand-off with real photos in §5 | ✅ |
| 10 | Docs: `mobile_usb_intake.md`, quickstart_demo, camera_setup, README, milestone-25 report | `docs/mobile_usb_intake.md`, this report, `docs/quickstart_demo.md`, `docs/camera_setup.md`, `docs/api.md` §M25, `README.md` | ✅ |

---

## 1. Summary

M25 is the smallest reliable bridge between "a phone photograph of a pack" and
"a committed stock receipt" on a Storeye edge node that the shopkeeper does not
need to touch. A lightweight watcher watches a USB intake folder; every new,
complete, non-duplicate image is fed through the **existing M17 pipeline**
(`scan_package`: pyzbar barcode → PaddleOCR → ExpiryParser → local catalog
lookup) and appears on the Smart Batch Receiving screen as a normal candidate
that still requires the M17 human confirmation.

Delivered:

- background **file watcher** (polling thread) with stability wait, validation,
  deterministic content-hash de-duplication and retention,
- **job store** (only small JSON metadata persists; never images), states
  `DETECTED → … → REVIEW_REQUIRED → CONFIRMED/PROCESSED/FAILED`,
- `MobileIntakeService` facade + **global manager** wiring the existing
  `BatchIntakeService(store_id=None)` as the scanner,
- **read-mostly REST API** (`/api/mobile-intake/...`); committing still happens
  only through `POST /api/batch-intake/confirm` (M17),
- **frontend "Mobile Capture · USB intake" panel** on the Smart Batch Receiving
  screen (status, pending candidates, one-click **Review candidate**, demo queue),
- demo scenario **`MOBILE_USB_RECEIVING`** + `demo-reset` hygiene hook,
- an **offline-generated watermarked demo package** (deterministic bytes) that
  exercises the watcher with the same bytes as a real USB copy,
- operator + milestone documentation and a full regression run.

**No runtime downloads, no cloud, no new models, no images in PostgreSQL.** The
phone is a camera; the laptop remains the edge computer.

## 2. Architecture

```
       phone 📱 (camera only)                   edge node (all compute)
 ┌────────────────────────┐   USB copy    ┌──────────────────────────────────────────┐
 │ photograph the pack    │ ────────────▶ │ <intake_dir>/          (any-name .jpg)   │
 │ then drag the photo out│               │    watcher polls @ 1s, size-settles 2s   │
 └────────────────────────┘               │    validate (jpg/png/webp, ≤15MB, intact)│
                                          │    sha256(idempotency)                    │
                                          │    copy → processing/, then M17           │
                                          │    scan_package()  (READ-ONLY)            │
                                          │      pyzbar → catalog lookup (identity)   │
                                          │      PaddleOCR → ExpiryParser (candidate) │
                                          │         │                                 │
                                          │    job REVIEW_REQUIRED  ◀── JSON index    │
                                          │         │ (frontend /app/receive)         │
                                          │      human edits + types quantity         │
                                          │         ▼                                 │
                                          │    POST /api/batch-intake/confirm         │
                                          │    BatchService + InventoryService in     │
                                          │    ONE atomic transaction → PostgreSQL    │
                                          └──────────────────────────────────────────┘
```

Key invariants (unchanged from M17, machinery newly added):

1. **No mutation before confirmation.** The watcher never commits anything;
   the only mutation path is the existing human-confirmed M17 endpoint.
2. **Barcode = identity only**; product resolution never auto-creates.
3. **OCR output is always a candidate** with editable fields and human quantity.
4. **Deterministic idempotency** — identical bytes are detected by `sha256`
   hash: one review job, never a second.
5. **Metadata-only persistence** — JSON index + file moves; zero image bytes in DB.

## 3. Delivered components

### Backend — `backend/app/services/mobile_intake/`

| File | Role |
|------|------|
| `errors.py` | `MobileIntakeError`, `IntakeFileRejected`, `UnsupportedFileError`, `FileTooLargeError`, `CorruptImageError`, `IntakeJobNotFound`, `IntakeDuplicateError`. |
| `intake_models.py` | `JobState` (`DETECTED`, `WAITING_FOR_COPY`, `PROCESSING`, `SCANNING`, `OCR_PROCESSING`, `REVIEW_REQUIRED`, `CONFIRMED`, `PROCESSED`, `FAILED`), `IntakeJob`, `JobsStore` (atomic tmp+rename JSON index). |
| `intake_watcher.py` | Polling thread: `scan_dir_once`, stability wait, validation, `sha256`, move, M17 scan, duplicate/retention rules. |
| `file_stability.py` | `wait_until_stable` — waits for size quiescence (2 s default). |
| `validation.py` | `sanitise_filename`, `sha256_bytes`, `file_size_ok`, `validates_as_image` (cv2 decode probe), supported-ext policy. |
| `intake_service.py` | Facility: `start/stop/scan_now/status/list_jobs/get_job/close_job/rescan/queue_demo_file/reset_demo_state`. |
| `manager.py` | Global singleton + `configure_intake_manager/reset_intake_manager/get_intake_manager`; default scanner `BatchIntakeService(store_id=None)` (DB-backed). |
| `demo_image.py` | Deterministic watermarked demo package bytes (Code-39 `8901063001015`, MRP ₹240, MFG `08/2026`, EXP `08/2027`, BATCH `M25-DEMO-01`). |

Supporting: `backend/app/utils/code39.py` (shared offline Code-39 renderer, used
by both the demo package and the existing test fixture
`backend/tests/_barcode_fixture.py`).

### Config (`backend/app/core/config.py` + root `.env.example`)

`STOREYE_INTAKE_DIR` (default `""` → `DATA_DIR/intake`), `INTAKE_MAX_MB=15`,
`INTAKE_STABILITY_SECONDS=2.0`, `INTAKE_WATCH_INTERVAL_SECONDS=1.0`,
`INTAKE_RETENTION_DAYS=7`, with value validators.

### API (`backend/app/schemas/mobile_intake.py`, `api/routers/mobile_intake.py`)

Registered in `app/main.py`; lifespan starts/stops the watcher
(`"pytest" not in sys.modules`). Errors: `IntakeJobNotFound`→404,
`MobileIntakeError`→409.

| Endpoint | Purpose |
|----------|---------|
| `GET  /api/mobile-intake/status` | monitoring, `watcher_alive`, dirs, `watched_at`, counters. |
| `GET  /api/mobile-intake/jobs` | job list (rehydrated candidates). |
| `GET  /api/mobile-intake/jobs/{job_id}` | single job. |
| `POST /api/mobile-intake/jobs/{job_id}/close` | mark review handled → `PROCESSED`. |
| `POST /api/mobile-intake/jobs/{job_id}/rescan` | retry a failed job from stored copy. |
| `POST /api/mobile-intake/demo-queue` | [demo mode + `X-Demo-Reset-Key`] enqueue watermarked demo package. |

### Demo integration

- `SCENARIO_MOBILE_USB_RECEIVING` in `demo_data.py` / `demo_scenarios.py`
  (13th scenario, category `receiving`, focus `/app/receive`).
- `demo.py` activate handler queues the demo package when the watcher is live.
- `demo_reset.py` `_reset_mobile_intake_demo_state()` removes only demo-intake
  artifacts (skipped under pytest; idempotent).
- `DemoActivationResult` carries an optional `mobile_intake_demo` field.

### Frontend (`frontend/src`)

- `lib/api/mobileIntake.ts` — `mobileIntakeApi` (status/jobs/job/close/rescan/
  demo-queue with `X-Demo-Reset-Key`).
- `lib/api/types.ts` — `MobileIntakeStatus`, `MobileIntakeJob`,
  `MobileIntakeJobList`, `MobileIntakeJobState`, `MOBILE_USB_RECEIVING` key,
  `DemoActivationResult.mobile_intake_demo`.
- `pages/ReceiveSmart.tsx` — live **Mobile Capture · USB intake** card (poll 3.5 s):
  watcher state + counters, waiting candidates, **Review candidate** loads the
  job's candidate into the existing M17 review form, demo queue, errors/notes.
  Quantity is never prefilled.
- `DemoControlCenter` renders the 13th scenario automatically (grid is
  backend-driven).

## 4. Verification — automated

| Suite | Result |
|-------|--------|
| `tests/test_mobile_intake.py` (new, `no_db`) | **36 passed** (4.3 s) — validation, stability, jobs index, watcher happy path + every rejection, duplicate/idempotency incl. duplicate-of-failed, close/rescan transitions, demo-reset isolation, catalogue determinism + unknown-slug fallback, HTTP layer + reset-key guard + product selection. |
| `tests/test_mobile_intake_real_ai.py` (new, `pg` + `real_ai`) | **1 passed** — full pipeline with real zbar + PaddleOCR on a seeded demo store for BOTH catalogue packs: Aashirvaad (queue → REVIEW_REQUIRED: barcode `8901063001015`, EXP `2027-08-01`, BATCH `M25-DEMO-01`, MRP `240.00`, labels+warnings) and Amul Milk 1L (`8901262030003`, BATCH `M25-DEMO-02`) — each confirmed via M17 `confirm_receipt` (batch + movement `quantity_change`), both closed, then a duplicate is suppressed (no double-receive). |
| Full backend regression | **415 passed** (378 at M23 baseline + 36 + 1). |
| `alembic check` | clean at head `19c835a1a344` (no schema change — bridge is data-folder + JSON only). |
| Frontend gates | `npx tsc -b` clean · **121 vitest passed** (119 + 2 new) · `npm run build` green. |
| New frontend tests | Watch panel renders; **Review candidate** prefills the M17 form and confirm stays disabled until quantity is typed; demo-queue sends `X-Demo-Reset-Key: storeye-demo-reset` and shows the note. |

## 5. Verification — live end-to-end (this machine, real services)

```
$ ./scripts/storeye start
 ok  PostgreSQL   running (.pgdata, port=5433)      ok  Backend healthy :8000
 ok  Frontend ready :5173
$ curl -s localhost:8000/api/mobile-intake/status
{"monitoring":true,"watcher_alive":true,"intake_dir":"…/backend/data/intake/intake",…}
$ curl -s -X POST localhost:8000/api/mobile-intake/demo-queue -H "X-Demo-Reset-Key: storeye-demo-reset"
{"queued":true,"filename":"storeye-demo-package-….jpg","size":178990,
 "sha256":"ca8a227ba6…","demo":true,"note":"… reused by the watcher."}
$ sleep 15 && curl -s localhost:8000/api/mobile-intake/jobs
[{"job_id":"d000d8b04bae","state":"REVIEW_REQUIRED","demo":true,"acceptable":true,
  "reason":"Barcode matched product 'Aashirvaad Atta 5kg'.",
  "candidate":{"barcode":"8901063001015","product_name":"Aashirvaad Atta 5kg",
   "batch_number":"M25-DEMO-01","expiry_date":"2027-08-01","expiry_date_precision":"month",
   "mrp":"240.00","confidence":0.983,"labels_found":["expiry","manufacturing","batch","mrp"]}}]
$ curl -s localhost:8000/api/mobile-intake/status   # {"scans":1,"active_jobs":1,…}
$ ./scripts/storeye stop   # PostgreSQL + backend + frontend stopped cleanly
```

The same transition was also exercised earlier at the service layer with a
second copy of the identical file: one review job total, second copy
`PROCESSED duplicate_of` (no double-receive). `demo-queue` with
`{"product":"amul"}` queues the second seeded pack (Amul Milk 1L,
`8901262030003`, BATCH `M25-DEMO-02`); both catalog packs resolve through the
real zbar + PaddleOCR in the automated E2E.

### Real local photo (filesystem-level hand-off)

Two real photos from `data/datasets/shelves` were copied into the intake
folder (`cp` = exactly what a USB drag produces at the filesystem level):

```
$ cp "data/datasets/shelves/images/WhatsApp Image … (1).jpeg"  backend/data/intake/intake/drag-over.jpg
  → job FAILED  "Image 636x422 is too small (short side 422px < 480px)…"   (honest gate)
$ cp "data/datasets/shelves/images/WhatsApp Image ….jpeg"        backend/data/intake/intake/real-photo.jpg
  → job REVIEW_REQUIRED  acceptable:false  "Unable to confidently read package information.
    Retake the photo (flat, well-lit, filling the frame) or enter the values manually."
```

Both are correct M17 semantics: a far shelf photo is genuinely not a close-up
pack photo, so the gate rejects too-small frames and the honest fallback says
so when barcode + OCR yield nothing. The full success path is proven by the
deterministic close-up demo packs (both products) in the automated E2E.

## 6. Rollback / disable

- `STOREYE_INTAKE_DIR=` (empty) is unchanged default behaviour — the watcher is
  harmless without content. To stop it outright, remove/rename the intake root;
  the watcher re-sweeps only when a directory reappears.
- No migration was added (no schema change), so rollback = revert the M25 commit.

## 7. Outputs

- `backend/app/services/mobile_intake/**`, `backend/app/utils/code39.py`
- `backend/app/config` additions, `backend/app/schemas/mobile_intake.py`,
  `backend/app/api/routers/mobile_intake.py`, errors/main/router wiring
- demo scenario + reset hook + `docs/mobile_usb_intake.md`
- `frontend/src/lib/api/mobileIntake.ts`, types, `ReceiveSmart.tsx` panel
- tests: `test_mobile_intake.py` (34), `test_mobile_intake_real_ai.py` (1),
  frontend `ReceiveSmart.test.tsx` +2

## 8. Test matrix (exact)

| Area | Count |
|------|-------|
| Backend total | **415 passed** |
| — existing M0–M23 | 378 |
| — new M25 (`no_db`) | 36 |
| — new M25 real-AI (`pg`, `real_ai`, both catalogue packs) | 1 |
| Frontend total | **121 passed** |
| — existing M0–M23 | 119 |
| — new M25 (ReceiveSmart UI panel) | 2 |
| Type/build | `tsc -b` clean · build green |
| Migrations | `alembic check` clean (head `19c835a1a344`) |

## 9. Known limitations / NOT VERIFIED

- **PHYSICAL USB TEST: NOT VERIFIED.** No real Android/iOS cable hand-off was
  performed on this machine. What IS proven: the exact filesystem-level byte
  path a USB copy produces (watched folder → stability → validation → real M17
  pipeline) was run live with two real local photos (§5) plus both demo packs,
  and the automated E2E covers the full success + reject + duplicate routes.
  The only remaining unknown is per-device OS-side USB enumeration, not
  Storeye behaviour.
- **Demo catalogue is small by design**: two seeded packs (Aashirvaad Atta 5kg,
  Amul Milk 1L). Adding a label is a two-line entry in
  `demo_image.DEMO_PACKAGES` plus a seeded product with the same barcode.
- `INTAKE_RETENTION_DAYS` sweeps processed/failed jobs **only** — active
  `REVIEW_REQUIRED` jobs are never auto-cleaned (intentional).
- Filename sanitisation is conservative: anything not `[A-Za-z0-9._-]` is
  rewritten; no traversal is possible.
- Demo-queue requires the watcher to be **running** and demo mode. If it is not
  running, activation reports `queued: false` instead of failing the scenario.
- Same accepted M17/OCR caveats carry over (first PaddleOCR cache bootstrap on
  a fresh machine; low-contrast or too-far labels fail the strict quality gate,
  and the honest fallback message tells the operator to retake the photo).
- No M24 exists in this repository line; M23 remains the immediately preceding
  milestone and its deliverable contracts are all preserved (415 regression
  proves it).