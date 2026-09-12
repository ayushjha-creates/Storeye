# Storeye Backend Test-Database Architecture

Audit + correction of which database the Storeye backend tests actually run
against, and the guarantees that keep production data safe.

## Authoritative data architecture (unchanged)

```
Frontend (React/Vite)
    ↓  /api over HTTP
FastAPI routers
    ↓  Depends(get_db)  (app/api/deps.py)
SQLAlchemy 2.0 sessions  (app/db/session.py)
    ↓
PostgreSQL 18            (one authoritative local DB per store: `storeye`)
    ↑
Alembic migrations       (alembic/versions/*)
```

**One authoritative PostgreSQL database per edge deployment.** No Supabase, no
second business database. The legacy SQLite/SQLModel stack
(`app/core/database.py`) is only used by `/api/health`, `/api/ready`,
`/api/metrics` and is intentionally left as documented legacy — never on any
business code path.

## Test classification (backend/tests)

| Category | Marker | Files | Count | Database |
|----------|--------|-------|-------|----------|
| A. Production/business-path | `pg` | test_api, test_database, test_inventory_domain, test_observations, test_reconciliation, test_intelligence, test_migrations | 108 | **PostgreSQL `storeye_test`** via `TEST_DATABASE_URL` |
| B. Legacy SQLite diagnostics | `legacy_sqlite` | test_foundation | 12 | SQLite temp dir (tests the legacy stack itself) |
| C. AI/model, no database | `no_db` | test_expiry_parser | 24 | none — pure unit tests |

## Corrections made

- Added `backend/pytest.ini` registering the three markers (`pg`,
  `legacy_sqlite`, `no_db`) for explicit classification.
- Each test module now declares its marker (no more implicit assumptions).
- `backend/tests/conftest.py` gained a **session-wide test-database guard**:
  - `TEST_DATABASE_URL` must be a PostgreSQL URL (refuses `sqlite://...`);
  - the database name must not be the production `storeye` database;
  - failure is loud (no silent SQLite/TempDB fallback).
  Verified: pointing `TEST_DATABASE_URL` at `storeye` or at a SQLite URL
  aborts the suite with `RuntimeError`.
- Added `backend/tests/test_migrations.py` (`pg`): verifies the **full Alembic
  chain** `4cafd848b801 → c3a7600b329b → e31098126b9c → acf54c2aa5f9 (head)`
  can build the schema on a clean `storeye_test` public schema, that
  `downgrade base` empties the schema, and that re-`upgrade head` reproduces
  it. Head = **`acf54c2aa5f9`**.
- `scripts/run-tests.sh` now: checks `alembic heads`, applies `alembic
  upgrade head` to the test DB, runs `alembic check` (no model↔migration
  drift), then runs pytest. (Also fixed its working-directory resolution.)

## Isolation guarantees

- Tests create/drop **only** the `storeye_test` database's schema — the
  production `storeye` database is never opened by the test suite.
- The conftest guard is belt-and-braces: even a misconfigured
  `TEST_DATABASE_URL` cannot point the suite at `storeye`.

## Verification (last full run)

- `alembic heads` → `acf54c2aa5f9 (head)`.
- `alembic check` → “No new upgrade operations detected” (no drift).
- `pytest tests/` → **144 passed** = 108 `pg` + 12 `legacy_sqlite` + 24 `no_db`,
  all against PostgreSQL `storeye_test` for business path tests.
- Frontend: `npm test` → 40 passed; `npm run build` (tsc + vite) → clean.
- Live M12 stack: Vite SPA → proxy → FastAPI → PostgreSQL `storeye`; all
  `/api/*` endpoints used by the M12 pages return 200 with real seeded data.

## Remaining legacy SQLite dependencies

- `app/core/database.py` (SQLModel) — supports `/api/health`, `/api/ready`,
  `/api/metrics` only; read-only diagnostics.
- `app/api/health.py` — the only router using the legacy session.
- `backend/tests/test_foundation.py` — the only test file using the legacy
  stack, deliberately, marked `legacy_sqlite`.
- No business route uses SQLite: all 13 business routers depend on
  `app.api.deps.get_db()` → PostgreSQL.