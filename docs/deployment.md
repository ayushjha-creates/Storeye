# Storeye — Deployment Guide

Storeye is a single-node, offline-first edge deployment:

```
[ cameras ] ──▶ Edge Node (this repo)                ──▶ LAN browser
                 ├─ PostgreSQL (business data)
                 ├─ FastAPI + service layer (API)
                 ├─ AI runtime (YOLO / OCR / Re-ID, optional)
                 └─ React frontend (static build)
```

There is **no cloud dependency**. Internet loss is the normal operating state.

---

## 0. Quick start (M23 one-click)

```bash
cp .env.example backend/.env      # then edit backend/.env if needed
./scripts/setup.sh                # deps + project PostgreSQL (:5433) + migrations + model check
./scripts/storeye start           # PostgreSQL + backend (:8000) + frontend (:5173)
./scripts/storeye seed            # load the deterministic demo store
./scripts/storeye status          # per-component health + URLs
./scripts/storeye doctor          # full environment readiness report
./scripts/storeye stop            # graceful stop (app + project PostgreSQL)
```

Every day-2 operation has a dedicated script — see the `scripts/` table in
[`quickstart_edge.md`](quickstart_edge.md) and readiness/diagnostics docs:
[`quickstart_demo.md`](quickstart_demo.md) · [`quickstart_edge.md`](quickstart_edge.md) ·
[`model_assets.md`](model_assets.md) · [`camera_setup.md`](camera_setup.md) ·
[`backup_restore.md`](backup_restore.md) · [`update_rollback.md`](update_rollback.md).

---

## 1. Prerequisites

| Component | Version / notes |
|-----------|-----------------|
| Python | 3.9+ (repo developed on 3.9) |
| PostgreSQL | 14+ (repo developed on PostgreSQL 18) |
| Node.js | 18+ (frontend build only) |
| Optional AI | `ultralytics` YOLO weights, PaddleOCR, OpenVINO — auto-detected |
| System | macOS (arm64 verified) / Linux; **Windows not claimed** |

## 2. Configuration

Configuration comes from environment variables (optionally `backend/.env`).
All values are validated at startup (`backend/app/core/config.py`).

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | *(unset)* | **Required.** Business PostgreSQL, e.g. `postgresql+psycopg2://storeye@localhost:5433/storeye`. Must be a PostgreSQL URL — `sqlite://` is rejected. |
| `ENVIRONMENT` | `development` | `development` \| `test` \| `production`. |
| `STRICT_STARTUP` | `false` | When true (or `ENVIRONMENT=production`), startup **fails** on bad config / unreachable PostgreSQL / schema behind Alembic head. |
| `CORS_ORIGINS` | `["http://localhost:5173","http://localhost:3000"]` | Allowed browser origins (http/https only). |
| `LOG_LEVEL` | `INFO` | `DEBUG`\|`INFO`\|`WARNING`\|`ERROR`\|`CRITICAL`. |
| `DEMO_MODE` | `true` | Enables `/api/demo/*`. Set `false` to disable demo endpoints entirely (they 404). |
| `DEMO_RESET_KEY` | `storeye-demo-reset` | `X-Demo-Reset-Key` value required by demo mutating endpoints. **Change in any shared deployment.** |
| `REID_ENABLED` | `true` | Anonymous cross-camera Re-ID. `false` = local track ids only. |
| `REID_PROVIDER` | `torch` | `stub` \| `torch` \| `openvino`. |
| `REID_SIMILARITY_THRESHOLD` | `0.72` | `[0,1]`; must be ≤ `REID_HIGH_CONFIDENCE_SCORE`. |
| `REID_HIGH_CONFIDENCE_SCORE` | `0.86` | `[0,1]`; must be ≥ similarity threshold. |
| `REID_MAX_TIME_GAP_SECONDS` | `120` | Max gap for an association. |
| `GLOBAL_PERSON_TIMEOUT_SECONDS` | `1800` | Idle seconds before an anonymous identity is forgotten. |
| `REID_UPDATE_INTERVAL_SECONDS` | `10` | Re-embed cadence for stable tracks. |
| `LOW_STOCK_THRESHOLD`, `EXPIRY_WARNING_DAYS`, `INSIGHT_*` | see config | Retail/insight rule thresholds (non-negative). |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | Backend bind address / port (scripts honour `STOREYE_HOST` / `STOREYE_PORT`). |
| `STOREYE_FRONTEND_PORT` | `5173` | Frontend dev-server port used by the scripts. |
| `TEST_DATABASE_URL` | `…/storeye_test` | Isolated test database (development only; conftest refuses `storeye`). |
| `PGHOST` / `PGPORT` / `PGUSER` / `PGDATA` / `DB_NAME` | `localhost` / `5433` / `storeye` / `.pgdata` / `storeye` | Back the `scripts/*.sh` PostgreSQL helpers. |
| `EDGERETAIL_DATA_DIR` / `EDGERETAIL_DB_PATH` | `backend/data` | Legacy SQLite diagnostics only — never the business DB. |

> **Secrets:** no credentials are hard-coded. Keep `DATABASE_URL` and a
> non-default `DEMO_RESET_KEY` in the environment (or a git-ignored `.env`),
> never in source control.

## 3. Database setup

One command (safe, idempotent): init/start the project PostgreSQL, create both
databases, and migrate:

```bash
./scripts/storeye start        # ensures PostgreSQL + applies nothing yet
./scripts/storeye migrate      # alembic upgrade head + check
```

Manual equivalent:

```bash
export DATABASE_URL="postgresql+psycopg2://storeye@localhost:5433/storeye"
cd backend

# Apply the full migration chain
./.venv/bin/python -m alembic upgrade head

# Verify models match migrations (should print no new upgrade operations)
./.venv/bin/python -m alembic check

# Load the deterministic demo dataset (idempotent; --reset to rebuild)
./.venv/bin/python -m scripts.seed_demo          # or: --reset
```

The canonical demo seed produces **22 insights / 8 alerts / 5 insight-generated
alerts / 234 observations** for the `Storeye Demo Mart` store.

## 4. Start the backend

Preferred (background daemon with pid file + logs):

```bash
./scripts/storeye start            # starts PostgreSQL, backend, frontend
./scripts/storeye status           # health of each component
```

Foreground (development):

```bash
export DATABASE_URL="postgresql+psycopg2://storeye@localhost:5433/storeye"
export ENVIRONMENT=production        # makes startup strict
./scripts/start-backend.sh           # or:
cd backend && ./.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Startup order (see `backend/app/core/startup.py`):

1. Validate configuration.
2. Probe PostgreSQL connectivity.
3. Compare the DB Alembic revision with the scripted head.
4. Initialise the legacy diagnostics DB and routers.
5. Load the AI runtime lazily (never blocks the business API).

In strict mode any of steps 1–3 failing raises and the process refuses to serve.

## 5. Start the frontend

```bash
cd frontend
npm install
npm run build          # production static build → frontend/dist
npm run dev            # dev server on :5173
```

Serve `frontend/dist` with any static server. Point the UI at the API via the
existing API base configuration (`frontend/src/lib/api/client.ts`).

## 6. Process management, logs & data

The `scripts/` suite backgrounds components with pid files and rotates logs:

| Command | What it does |
|---------|--------------|
| `./scripts/storeye start` | ensure PostgreSQL, start backend (:8000) + frontend (:5173) |
| `./scripts/storeye stop` | graceful SIGTERM→SIGKILL for tracked processes + stop PG (`--keep-db` to leave it) |
| `./scripts/storeye stop --clean-orphans` | also kills **untracked** uvicorn/vite left by killed sessions |
| `./scripts/storeye status` | per-component health + `/api/system/status` summary |
| `./scripts/storeye restart` | `stop` then `start` |
| `./scripts/storeye logs [backend\|frontend\|postgres]` | tail the runtime log |

Runtime artifacts (all git-ignored):

```
logs/backend/   uvicorn + postgres.log + backend.pid
logs/ai/        reserved for AI-runtime logs
logs/frontend/  vite log + frontend.pid
data/           demo fixtures / videos / imports
.pgdata/        project-local PostgreSQL cluster
backups/        pg_dump archives
```

`stop` only signals PIDs whose recorded command matches our known binaries
(`uvicorn`, `vite`), so unrelated services on the box are never touched.

## 7. Verify a deployment

| Check | Command / URL | Expected |
|-------|---------------|----------|
| Process alive | `GET /api/health` | `200` |
| Business readiness | `GET /api/system/status` | `status: OK`, `database.reachable: true`, `migration_current: true` |
| Legacy diagnostics | `GET /api/ready`, `GET /api/metrics` | `200` (SQLite diagnostics only) |
| Schema in sync | `alembic check` | `No new upgrade operations detected.` |
| Data integrity | `python -m scripts.integrity_check` (from `backend/`) | exit `0`, `status: OK` |
| Demo catalog | `GET /api/demo/scenarios` | 12 scenarios (when `DEMO_MODE=true`) |
| Environment | `./scripts/storeye doctor --json` | `overall: READY` (or WARN-only `DEGRADED`) |
| Model assets | `./scripts/storeye models` | all checks `[ OK ]` |

`/api/system/status` returns `503` when configuration is invalid or PostgreSQL is
unreachable, and `200` with `DEGRADED` when the schema is behind head.

## 8. Operations

- **Migrations:** always `./scripts/storeye migrate` (`alembic upgrade head`) before starting a new version.
- **Backups:** `./scripts/storeye backup` nightly — see `docs/backup_restore.md`.
- **Integrity audit:** run `python -m scripts.integrity_check` after restores or
  suspected corruption. It is read-only and safe to run at any time.
- **Updates/rollback:** `docs/update_rollback.md` — code-only vs schema rollback.
- **Model assets / offline staging:** `docs/model_assets.md` (STATE A/B/C).
- **Logs:** structured by `LOG_LEVEL`; startup notices are logged as warnings.
  Directories listed in §6; rotate with `logrotate`/`newsyslog`.
- **AI optionality:** if model weights/libraries are missing the AI runtime
  degrades to disabled; the API and business flows continue to work.

## 9. Security posture (read this)

Storeye has **no built-in authentication**. It is designed for a trusted,
single-tenant edge node.

- Bind to localhost or a trusted LAN only, or
- Put it behind a reverse proxy (nginx/Caddy) that terminates TLS and enforces
  authentication, and set `CORS_ORIGINS` to the real UI origin.
- Change `DEMO_RESET_KEY` and set `DEMO_MODE=false` on non-demo deployments.
- Never expose PostgreSQL directly.
- `./scripts/storeye doctor` flags production deployments left on demo defaults.

## 10. Running the test suite

```bash
./scripts/storeye test
# or explicitly:
cd backend
TEST_DATABASE_URL="postgresql+psycopg2://storeye@localhost:5433/storeye_test" \
  ./.venv/bin/python -m pytest -q
cd ../frontend && npx tsc -b && npx vitest run && npm run build
```

`TEST_DATABASE_URL` must be PostgreSQL and must **not** be the production
`storeye` database — a conftest guard fails the suite otherwise.
