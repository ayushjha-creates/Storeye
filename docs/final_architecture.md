# Storeye — Final Architecture (M0–M22)

This is the consolidated architecture of the completed platform. It supersedes
the per-milestone detail while remaining consistent with
`docs/architecture.md`, `docs/database.md`, `docs/edge-ai.md`,
`docs/privacy_architecture.md` and `docs/api.md`.

## 1. One-sentence model

> Computer vision produces **observations**; deterministic services turn
> observations and business data into **intelligence**; humans turn
> intelligence into **business actions** — all on a single offline edge node
> with PostgreSQL as the source of truth.

## 2. Layered view

```
┌──────────────────────────────────────────────────────────────────────┐
│ Presentation — React 18 + Vite + TS + Tailwind (frontend/)            │
│   Auth/Edge providers · AppShell · ErrorBoundary · OfflineBanner      │
│   Pages: Dashboard, Live Store, Cameras, Observations, Inventory,     │
│          Smart Receiving, Billing, Products, Customers, Product/Shelf │
│          Intelligence, Alerts, Journeys, Insights, Demo Control,      │
│          Reports, Settings                                            │
└───────────────▲──────────────────────────────────────────────────────┘
                │ HTTP JSON
┌───────────────┴──────────────────────────────────────────────────────┐
│ API — FastAPI (backend/app/api)                                       │
│   domain routers (inventory, products, billing, …) · edge · alerts ·  │
│   insights · journeys · demo · health (legacy) · system (M22 ready)   │
│   consistent exception handlers (app/api/errors.py)                   │
└───────────────▲──────────────────────────────────────────────────────┘
                │ service calls only
┌───────────────┴──────────────────────────────────────────────────────┐
│ Service layer (backend/app/services)                                  │
│   inventory · batch_intake · observations · intelligence · insights · │
│   alerts · journeys · reconciliation · demo · integrity (M22)         │
└───────────────▲──────────────────────────────────────────────────────┘
                │ SQLAlchemy models
┌───────────────┴──────────────────────────────────────────────────────┐
│ Persistence — PostgreSQL (backend/app/db, backend/alembic)            │
│   stores, cameras, zones, shelves, products, inventory, movements,    │
│   batches, planograms, customers, sales, bills, notifications,        │
│   alerts, observations, reconciliation_results, journeys (4 tables),  │
│   insights, demo_scenario_state                                       │
└───────────────▲──────────────────────────────────────────────────────┘
                │ observations only (never business writes)
┌───────────────┴──────────────────────────────────────────────────────┐
│ Edge AI runtime (backend/app/edge)                                    │
│   camera workers · YOLO detect · ByteTrack · anonymous Re-ID (memory) │
│   shelf/product detector · OCR · expiry parser · annotator · workers  │
└──────────────────────────────────────────────────────────────────────┘
```

## 3. Request / processing flows

**Ingest (edge)**
`CameraWorker → detector (YOLO) → tracker → observations (+ optional Re-ID) →
ObservationWriter → observations table`. The writer never touches inventory.

**Intelligence (deterministic)**
`ProductIntelligence` / `ShelfIntelligence` read observations + planogram +
inventory and emit digests; `Expiry Intelligence` reads batches. These feed the
M16 `AlertService` (dedup by context) and the M20 `InsightEngine` (evidence +
recommended action, dedup by type/entity).

**Store intelligence (M20)**
`InsightEngine.evaluate()` evaluates all rules over existing rows in one atomic
reconcile: insights are upserted, the cached `STORE_HEALTH` summary is persisted
in the same cycle, and actionable insights create/refresh M16 alerts via the one
alert service. No operational data is mutated.

**Demo / scenarios (M21)**
`DemoScenarioEngine.activate(key)` → `reset_to_baseline` → scenario applier →
`InsightEngine.evaluate()` (single atomic reconcile) → persist
`demo_scenario_state` → commit. On error: rollback + baseline reset + re-raise.
Only stores with `Store.is_demo = true` are eligible.

**Business writes (human-confirmed)**
Inventory movements, batch creation, sales/billing and Smart Receiving are the
only paths that change business truth. Smart Receiving requires explicit human
confirmation of parsed OCR/expiry fields before committing.

## 4. Data model (PostgreSQL)

- **Reference:** stores (with `is_demo`), users, cameras, zones, shelves,
  products (with `ai_classes`), planograms.
- **Inventory:** inventory (aggregate per store/product), inventory_movements
  (append-only history), batches (with expiry + precision).
- **Commerce:** customers, sales, sale_items, bills, bill_items.
- **AI observations:** observations (person/product/text/expiry-metadata),
  reconciliation_results.
- **Anonymous journeys:** global_person_sessions, person_track_associations,
  zone_visits, person_camera_transitions.
- **Intelligence output:** alerts, insights, demo_scenario_state.

Migrations are the schema source of truth (`backend/alembic`, current head
`19c835a1a344`); `alembic check` must stay clean.

## 5. AI subsystems (all optional, all informational)

| Subsystem | Tech | Failure mode |
|-----------|------|--------------|
| Person detection | Ultralytics YOLO | disabled; pipeline idle |
| Tracking | ByteTrack | local ids only |
| Cross-camera Re-ID | ResNet18 / OpenVINO, **in memory** | disabled; local ids only |
| Shelf/product detection | YOLO | intelligence degrades to empty |
| OCR / expiry / barcode | PaddleOCR + parser | Smart Receiving shows "no read" |
| Annotation | OpenCV | raw stream unavailable |

No model output is ever written to a business table as truth.

## 6. Configuration & startup hardening (M22)

`app/core/config.py` validates every setting. `app/core/startup.py` enforces the
order config → PostgreSQL → Alembic head → app, strict in production. The
authoritative readiness endpoint is `GET /api/system/status`; the legacy
`/api/health|ready|metrics` endpoints remain for backward compatibility and
report only the diagnostics stack.

## 7. Integrity & diagnostics (M22)

`IntegrityCheckService` (`python -m scripts.integrity_check`) is a read-only
audit: orphaned foreign keys, negative/duplicate inventory, invalid batch dates,
alert lifecycle validity, camera config validity, demo isolation and a privacy
column assertion. It exits non-zero on any error.

## 8. Guarantees

1. Offline-first: no operational internet dependency.
2. Privacy-first: no identity/biometrics; no raw media or embeddings persisted.
3. Human-in-the-loop: AI advises, humans commit.
4. PostgreSQL is the single source of truth for business data.
5. Deterministic intelligence: rules over persisted rows; no LLM/generative
   evaluation.
6. Model swappability: providers/config, not code.
7. UUIDs on syncable entities; UTC timestamps.

## 9. Milestone index

M0–M11 core domain/API · M12/M18 frontend + demo showcase · M13/M14 edge AI +
camera dashboard · M15 product/shelf intelligence · M16 alerts · M17 Smart Batch
Receiving · M19 anonymous journeys · M20 store intelligence · M21 demo scenario
engine · **M22 production hardening & final integration** (config validation,
startup readiness, system status, integrity checks, UI error boundary, docs).
