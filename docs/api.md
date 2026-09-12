# EdgeRetail-IQ API

Milestone 11 adds a FastAPI backend that exposes the domain model
(15 entities) over HTTP. It is the foundation that will later back the web
frontend and the WhatsApp/SMS channel (later milestones).

## Stack

- **Router layer**: FastAPI + Pydantic v2 (Python 3.9 compatible — schemas/signatures
  use `Optional[T]`/`List[T]` from `typing`, never `T | None`).
- **Persistence**: SQLAlchemy 2.0 ORM against **PostgreSQL 18** (source of truth).
  Schema owned by Alembic migrations (see `docs/database.md` → legacy note at the
  bottom of this file).
- **Interactive docs**: `/docs` (Swagger UI) and `/redoc` are generated from the
  OpenAPI spec (`/openapi.json`).

## Running the server

Run from the `backend/` directory. `DATABASE_URL` must point at PostgreSQL
(see `.env.example` / settings in `app/core/config.py`):

```bash
# from backend/
export DATABASE_URL="postgresql+psycopg2://storeye@localhost:5433/storeye"
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Then open http://localhost:8000/docs.

> Note: the top-level app uses `get_db()` (PostgreSQL) for all business routes.
> The `/api/health`, `/api/ready`, and `/api/metrics` endpoints are legacy
> SQLite diagnostics and are preserved — see "Legacy / duplicate architecture".

## Conventions

- **JSON bodies**, field names snake_case.
- **IDs** are UUIDs; timestamps are ISO-8601 UTC.
- **Pagination/article lists**: list endpoints return
  `{"total": <int>, "items": [...]}`.
- **Errors**: consistent error envelope via `app/api/errors.py`:
  ```json
  {"detail": "Human readable message"}
  ```
  with these status-code mappings:

  | HTTP | Domain error (raised by service layer) |
  |------|----------------------------------------|
  | 422  | `InventoryValidationError`, `ObservationValidationError` |
  | 404  | `InventoryNotFoundError`, `ObservationNotFoundError` |
  | 409  | `DuplicateBatchError`, `BatchMismatchError`, DB `IntegrityError` (dup SKU, etc.) |
  | 500  | unexpected inventory/observation failures |

- **Auth**: not implemented yet. A dependency stub placeholder is in place so a
  real auth middleware can be dropped in during a later milestone.

## Engineered guarantees (Milestone 11 rules)

- Inventory **mutations** (receive/adjust/movement/batch) go exclusively through
  `InventoryService` / `BatchService` (domain rules + atomic transaction). The API
  never mutates inventory directly.
- The only batch route that touches the ORM directly is the batch **metadata**
  update (`PATCH /api/inventory/batches/{batch_id}`); it never changes the recorded
  quantity (stock counts are derived from movements).
- AI observations and reconciliation results are **informational only**. No route
  auto-converts `POSSIBLE_SHORTAGE`/`POSSIBLE_SURPLUS` into inventory mutations.
- Billing is **manual** (no AI/camera-generated bills). WhatsApp/SMS dispatch is a
  later milestone.

## Entity endpoint groups

### Stores, Users, Zones, Shelves, Products, Cameras, Customers, Bills, Notifications
Standard CRUD + list:
`GET/POST /api/{entity}`, `GET/PATCH/DELETE /api/{entity}/{id}` (Sales/GOT omitted where write-only).

List filters (subset by entity): `search`, `store_id`, `zone_id`, `shelf_id`,
`is_active`, `created_from`, `created_to`, plus pagination `offset`/`limit`
(default 0/100) and ordering `order_by`/`order`.

### Inventory (aggregate stock; read + batch endpoints)
- `GET  /api/inventory/stores/{store_id}/products/{product_id}` — current aggregate stock.
- `GET  .../summary` — quantity, value, weighted avg cost, variant counts.
- `GET  .../movements?batch_id=&reason=&kind=` — movement ledger.
- `GET  .../batches` — batches for that store+product.

### Inventory mutations (service-mediated; atomic)
- `POST /api/inventory/receive {store_id, product_id, quantity, unit_cost, supplier?, ref?}` — creates a batch, then credit-moves stock. Returns batch + movement.
- `POST /api/inventory/adjust {store_id, product_id, quantity, reason, ref?}` — signed adjustment (negative = write-off / damage).
- `POST /api/inventory/movements {store_id, product_id, quantity, kind: "IN"|"OUT"|"ADJUSTMENT", batch_id?, ref?}` — ledger entry; keeps aggregate in sync.
- `POST /api/inventory/batches {store_id, product_id, quantity, unit_cost, expiry?, supplier?, received_at?}` — create batch.
- `PATCH /api/inventory/batches/{batch_id}` — **metadata only** (expiry, supplier, etc.); does NOT change quantity.
- `PATCH /api/inventory/stores/{store_id}/products/{product_id}/reorder {reorder_level?, reorder_quantity?}` — set reorder policy.

### Smart Batch Receiving (M17; scan read-only, confirm atomic)
- `POST /api/batch-intake/scan` — **multipart** `file` (close-up package photo) + `store_id`
  form field. Local quality gate → barcode decode (pyzbar, product identity only) →
  PaddleOCR text → ExpiryParser → `{acceptable, reason, candidate}`. **Never mutates.**
  `ImageDecodeError`/`ImageQualityError`/`ScanValidationError` → 422;
  `OcrUnavailableError`/`BarcodeUnavailableError` → 503.
- `POST /api/batch-intake/confirm {store_id, product_id, quantity (>0), batch_number?,
  manufacturing_date?, expiry_date?, expiry_date_precision?, mrp?}` → 201
  `{movement, batch}` — one atomic transaction via `BatchService` + `InventoryService`
  (rollback on failure). Quantity is always human-entered; barcode never creates products.

Products carry a unique-per-store `barcode` field (migration `c4f5a6b7c8d9`) used by
the scan resolution.

### Observations (AI/detections; read-write but informational)
- `POST /api/observations` — ingest a camera observation (typed, per product/zone/shelf).
- `GET  /api/observations?...filters` — query `kind`, `confidence`, `status`, time window.

### Reconciliation (manual / informational)
- `POST /api/reconciliation/run {store_id, product_id?, snapshot_id?}` — run reconciliation (never mutates inventory).
- `GET  /api/reconciliation` — list results.
- `GET  /api/reconciliation/{result_id}` — single result incl. detected shortages/surpluses.

### Diagnostics (legacy)
- `GET /api/health` — app/model health.
- `GET /api/ready` — readiness probe.
- `GET /api/metrics` — runtime metrics.

### Demo showcase (M18; guarded, idempotent re-seed)
- `POST /api/demo/reset` — re-seeds the deterministic `Storeye Demo Mart` dataset.
  Requires header `X-Demo-Reset-Key: <DEMO_RESET_KEY>` (server-side env; default
  `storeye-demo-reset` used **only** in development). Without/with a wrong key → 403.
  Calls `scripts/seed_demo.reset_and_seed()` which deletes the demo store's data and
  re-creates an identical deterministic dataset (fixed UUIDs, see below), so repeated
  calls converge to exactly the same state — safe for demos.

## Error example (duplicate SKU)
```
POST /api/products {"store_id": "...", "sku": "MAGGI", "name": "x"}
-> 409 {"detail": "Product with SKU 'MAGGI' already exists in this store"}
```

## Request / response example (receive stock)
```
POST /api/inventory/receive
{"store_id": "<uuid>", "product_id": "<uuid>", "quantity": 24, "unit_cost": 12.5}
-> 201 {
  "batch": {...batch fields...},
  "movement": {"kind": "IN", "quantity": 24.0, "before": 0.0, "after": 24.0, ...}
}
```

## Legacy / duplicate architecture (IMPORTANT)

The codebase intentionally carries **two persistence stacks**. Milestone 11 added
the new PostgreSQL API but must NOT remove the legacy code:

| Concern | Legacy (old) | New (M11) |
|---------|--------------|-----------|
| Persistence | SQLModel + SQLite | SQLAlchemy 2.0 + PostgreSQL 18 |
| Session | `app/core/database.py` (`engine`, `init_db`, `close_db`) | `app/db/session.py`, `app/db/base.py` |
| Migrations | SQLModel metadata `create_all` | Alembic (own migrations) |
| Health/router data | `app/api/health.py` | `app/api/routers/*` via `app/api/deps.py` |

- The legacy SQLite stack is used ONLY by `/api/health`, `/api/ready`, `/api/metrics`
  and is exercised by the older tests. It is slated to be deprecated, not removed.
- `docs/database.md` (lines describing SQLite/SQLModel as the source of truth) is now
  **outdated** — PostgreSQL via Alembic is the source of truth. This document supersedes
  that view.
- `.env` is not committed/configured; `DATABASE_URL` must be provided in the
  environment for the PostgreSQL-backed business routes to function (health/ready/metrics
  work standalone against SQLite).
- The stale health model (`app/core/...` SQLite model) still references the old schema;
  it is intentionally left in place and documented here.

## Files created / modified (M11)

- `app/schemas/` — Pydantic schemas for all 15 entities + shared common schema.
- `app/api/deps.py` — `get_db()` dependency (rollback on error, close in finally).
- `app/api/errors.py` — exception→HTTP status handler registry.
- `app/api/routers/` — stores, users, cameras, zones, shelves, products, inventory,
  customers, sales, bills, notifications, observations, reconciliation.
- `app/main.py` — rewired: registers health + all entity routers under `/api`, wires
  error handlers, keeps CORS and startup/shutdown.
- `tests/test_api.py` — 21 DB-backed API tests (real PostgreSQL via test session overrides).

## Tests

The backend test suite is split into three explicit categories (see
`docs/backend_test_database.md` for the full audit):

- **`pg` (108 tests)** — production business/data-path tests. Run against the
  isolated **PostgreSQL** database `storeye_test` (via `TEST_DATABASE_URL`).
  PostgreSQL must be reachable on `localhost:5433`. There is **no silent
  SQLite fallback**: `conftest.py` fails the suite if `TEST_DATABASE_URL` is
  missing, non-PostgreSQL, or pointed at the production `storeye` database.
- **`legacy_sqlite` (12 tests)** — intentionally test the legacy
  SQLite/SQLModel diagnostics stack (`app.core.database` + `/api/health`,
  `/api/ready`, `/api/metrics`). Marked `legacy_sqlite`.
- **`no_db` (24 tests)** — pure unit tests (e.g. expiry parser), no database.

```bash
# from backend/ (uses storeye_test DB; TEST_DATABASE_URL default set in settings)
.venv/bin/python -m pytest tests/ -q
# => 144 passed (108 pg + 12 legacy_sqlite + 24 no_db)

# or the one-shot runner (alembic head check + upgrade head + drift check + pytest):
./scripts/run-tests.sh
```

Schema for the business tests is created by the **full Alembic migration
chain** (verified by `tests/test_migrations.py` against a clean `storeye_test`
public schema; head = `acf54c2aa5f9`). `alembic check` confirms zero model↔migration drift.

The API tests are verified non-vacuous by mutation testing: deliberately
breaking the "reconciliation never mutates inventory" guarantee and the
"duplicate -> 409" mapping both cause the corresponding tests to fail.

### Behavioral notes (confirmed by tests)
- `POST /api/inventory/adjust` returns **200** (no explicit status on route; the
  response is an `InventoryMovementRead`).
- `adjust` only enforces non-negative stock when the `require_sufficient_stock`
  flag is `true`; otherwise negative adjustments (write-offs/damage) are allowed.
- Sales/bills with an unknown store or product return **404**.
- Insufficient-stock adjustments return **422** (from the service `ValidationError`).
