# Milestone 16 — Alerts + Actionable Intelligence

**Date:** 2026-09-07
**Status:** ✅ Implemented and verified

---

## Summary

M15 turned real observations into honest product/shelf intelligence (possible shortage,
possible surplus, low shelf occupancy, possible misplacement, expiry risk, review
required, camera health). M16 turns those intelligence results into a **persistent,
queryable, offline-first alert system**: rules evaluate intelligence outputs into
`alerts` rows, shopkeepers acknowledge/resolve/dismiss them from the UI, and the same
inference results are reused — never re-running YOLO/OCR.

The alert layer is a pure computation over PostgreSQL data. It stays fully offline
(local FastAPI + Postgres, local React), makes no network calls, and **never mutates
inventory/batches/bills/sales** — alerts are informational and actionable, and every
screen says so.

## The M16 data flow

```
Existing observations (patterns + details)
   │
   └─▶ ProductIntelligenceService ──▶ shortage/surplus rules   ─┐
       ShelfIntelligenceService  ──▶ occupancy/misplacement    ├─▶ POST /api/alerts/evaluate
       ExpiryIntelligence        ──▶ expiry rules              │   (AlertRuleEngine, read-only
       ReconciliationResult      ──▶ review-required rule      │    over existing intelligence)
       Observation.written_at    ──▶ camera-heartbeat rule     ─┘
                                                                      │
                                          dedup (same store/type/context)│
                                                                      ▼
                                                          alerts (PostgreSQL)
                                                                      │
                       GET /api/alerts · POST /api/alerts            │
                       PATCH /{id} (metadata)                        ▼
                       POST /{id}/acknowledge|resolve|dismiss ──▶ React Alerts page
```

## Hard rules honoured

- **No notification channels.** No WhatsApp/SMS/email/push anywhere. The "alert" is a
  first-class DB entity with a shopkeeper UI — there is no outbound transport.
- **No cloud.** Alert creation, listing, filtering and lifecycle actions all run
  locally (`app/api/routers/alerts.py` + Postgres). No internet call exists in this
  flow.
- **No inference re-run.** Rules consume M15 `ProductIntelligenceService`,
  `ShelfIntelligenceService`, `MisplacementService`, `ExpiryIntelligence` and the
  persisted M13 `ReconciliationResult` snapshot. YOLO/OCR are never invoked by the
  alert layer.
- **No raw video in Postgres.** Evidence is metadata only — `details` JSONB
  (source, quantities, counting rule, expected/detected product, shelf code…).
- **Alert layer is read-only over business data.** It reads inventory, planograms and
  reconciliation snapshots but never creates/mutates inventory, inventory_movements,
  batches, bills or sales. Enforced by construction and covered by
  `test_alert_service_never_mutates_business_state`.
- **Legacy SQLite** still exists only for `/api/health`, `/api/ready`, `/api/metrics`.
- **Informational language.** Alert titles/messages use "Possible", "AI-estimated",
  "Informational — review before any adjustment". AI never produces "Confirmed
  shortage"/"Out of stock".

## Domain decisions (locked)

### Alert types
`SHORTAGE, SURPLUS, MISPLACEMENT, EXPIRY, LOW_SHELF_OCCUPANCY, SHELF_EMPTY,
CAMERA_OFFLINE, REVIEW_REQUIRED`

### Severity (independent of confidence)
`INFO, LOW, MEDIUM, HIGH, CRITICAL`
- SHORTAGE: ≥0.5 confidence → CRITICAL; ≥0.2 → HIGH; else MEDIUM
- SURPLUS: ≥0.5 → HIGH; ≥0.2 → MEDIUM; else LOW
- MISPLACEMENT: LOW
- SHELF_EMPTY (no visible product): CRITICAL — "refill now / ASAP"
- LOW_SHELF_OCCUPANCY (visible occupancy at/below half): occupancy <15% → HIGH else
  MEDIUM — "about to get empty, refill soon"
- EXPIRY: EXPIRED → HIGH; EXPIRING_SOON/EXPIRY_MONTH → MEDIUM
- CAMERA_OFFLINE: MEDIUM · REVIEW_REQUIRED: LOW

### Lifecycle
```
OPEN → ACKNOWLEDGED | RESOLVED | DISMISSED
ACKNOWLEDGED → RESOLVED | DISMISSED
RESOLVED/DISMISSED → terminal (no transitions)
```
Any invalid transition raises `InvalidStatusTransitionError` → 422.

### Dedup
Same `(store_id, alert_type, product_id, shelf_id, camera_id)` context on an existing
OPEN/ACKNOWLEDGED alert **updates** it (`last_detected_at`, severity, merged details)
instead of creating a duplicate. A terminal alert (RESOLVED/DISMISSED) never prevents a
new alert on the next evaluation.

### Rule wiring
- Shortage/surplus from `comparison_status` + confidence ≥ threshold (default 0.5);
  only mapped products.
- Misplacement only on planogram-based mapped products (`possible_misplacement`).
- Shelf fill: EMPTY_VISIBLE → `SHELF_EMPTY` (CRITICAL) and LOW_VISIBLE → 
  `LOW_SHELF_OCCUPANCY` (`refill_soon`). UNKNOWN (no AI evidence) never alerts. This
  rule also runs after `POST /api/reconciliation/run` (`evaluate_shelf_fill`,
  `trigger="reconciliation"`) so refilling surfaces as a reconciliation outcome; it
  writes only `alerts` rows, never stock.
- Review-required from a persisted `ReconciliationResult.status == REC_REVIEW` snapshot
  within the evaluation window.
- Expiry through `ExpiryIntelligence.reference_date` (injectable), threshold via
  `expiry_warning_days`.
- **CAMERA_OFFLINE is a documented, deterministic simulation**: an active camera with no
  observation written in the last `camera_stale_minutes` (default 60) raises
  "No detections from <camera>" at MEDIUM. This is a safe, engine-tested proxy for the
  real stale-heartbeat contract that the "physical" Edge Device FW (out of scope for
  this project) would publish — so the alert UI/API stays correct once a real
  camera-health signal exists.

## What was delivered

### Data layer
- `alerts` table (migration `d9e4a30f8b21`) — `alembic heads` = `d9e4a30f8b21`.
- `Alert` model: FK to stores (cascade delete); nullable camera/product/shelf FKs
  (cascade delete, `SET NULL` on store-implied deletes); generated UUID PK; enum
  alert_type/severity/status; confidence; first/last_detected_at; timestamps for
  ack/resolve/dismiss; `source_type`/`source_id`; `details` JSONB evidence; title+message.
- Indexes for status, severity, store, camera, product, fused context dedup lookup.

### Services (`app/services/alerts/`)
- `AlertRuleEngine` — evaluates all rules in one pass over intelligence + recon +
  camera heartbeats; returns `AlertRuleResult(generated|updated|skipped, alerts)`.
- `AlertService` — create, get, query (filters + pagination), patch metadata, lifecycle
  (ack/resolve/dismiss), and the no-mutation boundary. Errors in `errors.py`
  (`AlertValidationError`, `AlertNotFoundError`, `StoreyeAlertError` base).

### API (`/api/alerts`)
- `GET /api/alerts` — filters `store_id, camera_id, product_id, shelf_id, alert_type,
  severity, status, created_from, created_to` + `limit/offset` → `{total, items}`.
- `POST /api/alerts` — manual alert creation.
- `GET /api/alerts/{id}`, `PATCH /api/alerts/{id}` (metadata-only; status field is
  rejected).
- `POST /api/alerts/{id}/acknowledge | resolve | dismiss`.
- `POST /api/alerts/evaluate` — runs `AlertRuleEngine` for a store (`hours` window) →
  `{evaluated_at, store_id, hours, generated, updated, skipped, alerts}`.
- Errors: `AlertValidationError` → 422, `AlertNotFoundError` → 404,
  `StoreyeAlertError` → 500.

### Frontend
- `src/lib/api/alerts.ts` — `alertApi` (list/get/create/evaluate/acknowledge/resolve/
  dismiss) + label/order constants for filters.
- Components: `AlertSeverityBadge`, `AlertStatusBadge`, `AlertCard` (type/severity/
  status/title/message/context/confidence/detected time + lifecycle actions),
  `AlertList`, `AlertFilters`, `AlertDetail` (evidence modal).
- `src/pages/Alerts.tsx` — `/alerts` route: filterable inbox, "Evaluate now", ack/
  resolve/dismiss actions, evidence modal, stats (Alerts/Open/High-Critical). Nav entry
  in the AppShell (between Shelf Intel and Inventory).
- Integrations: Dashboard "Alerts" card (open + high/critical counts, recent alerts);
  CameraDetail "Alerts (this camera)" card with "View all →"; ProductIntelligence and
  ShelfIntelligence "related open alerts" banners linking to `/alerts`. All alert
  fetches are best-effort (fail silently) so older pages/tests stay green without
  stubbing `/api/alerts`.

## Verification

- Backend: `tests/test_alerts.py` — **34 tests** (create/validation/FK context, dedup
  & merge, context separation, filters+pagination, per-type rule generation + severity
  boundaries, confidence thresholds, no-guess unmapped, planogram-gated misplacement,
  low-shelf (incl. UNKNOWN no-alert), expiry windows, review window, CAMERA_OFFLINE
  (stale only / inactive excluded / camera-scoped), lifecycle incl. invalid transitions
  and re-alert after resolve, ack-still-dedups, and no-mutation invariants at service +
  API level).
- Full backend suite: **195 passed** (`pytest tests/ -q`), incl. migration
  up/downgrade round-trip (`EXPECTED_HEAD = d9e4a30f8b21`, `alerts` in
  `EXPECTED_TABLES`).
- Frontend: `npx tsc -b` clean; `npx vitest run` **72 passed** across 18 files (new:
  `Alerts.test.tsx`, Dashboard alerts card, CameraDetail camera alerts,
  Product/Shelf related alerts); `npm run build` succeeds.

## Known caveats (accepted)

- **CAMERA_OFFLINE simulation** — see rule wiring above. Real stale-heartbeat is a
  future hard-coded-device contract, out of scope.
- `alembic check` flags a whole-model diff unrelated to alerts (pre-existing
  `deadline`-style SQL-expression columns autogenerate as regular columns). Not
  changing as it would require a non-functional behavior-neutral migration; the
  `alerts` table itself round-trips cleanly.