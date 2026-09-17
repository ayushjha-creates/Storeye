# Storeye — Quickstart (Demo Showcase)

Get the Storeye demo running on a single machine in ~10 minutes. Everything is
local: PostgreSQL + FastAPI + React + the AI models. No cloud, no accounts.

---

## 1. Prerequisites (one time)

- macOS 14+ (Apple Silicon) **or** a Linux machine — verified on macOS 26.5.1
  arm64 and PostgreSQL 18. **Windows is not claimed/tested.**
- Python 3.9+ · Node.js 20+ · npm · PostgreSQL tools
  (`initdb`/`pg_ctl`... — on macOS: `brew install postgresql@18`).
- Optional AI speedup: `brew install zbar` (barcode decoding).

## 2. One-click setup

```bash
git clone <your Storeye repo> && cd Storeye
cp .env.example backend/.env          # or let setup.sh create it for you
./scripts/setup.sh                     # deps + project PostgreSQL + migrations + model check
```

`setup.sh` is idempotent and:
- creates `backend/.venv` + installs deps, runs `npm ci` in `frontend/`,
- initialises/creates the project-local PostgreSQL cluster in `.pgdata` (:5433),
- creates the `storeye` and `storeye_test` databases and applies migrations,
- checks the local model assets (never downloads at runtime).

## 3. Start everything

```bash
./scripts/storeye start      # PostgreSQL + backend (:8000) + frontend (:5173)
./scripts/storeye status     # health + URLs
```

- Dashboard: <http://localhost:5173>
- API health: <http://localhost:8000/api/health>
- Readiness:  <http://localhost:8000/api/system/status>

## 4. Seed the demo store

```bash
./scripts/storeye seed                 # idempotent (fixed UUIDs)
./scripts/storeye demo-reset --verify  # optional: prove reset determinism
```

Baseline demo data: **22 insights / 8 alerts / 5 insight-generated alerts /
234 observations** for the `Storeye Demo Mart` store.

## 5. Walk through the showcase

1. Open the dashboard and sign in with the demo account:
   - email `demo@storeye.local` · password `StoreyeDemo@123`
2. Open the **Demo** view (guided scenario player). Twelve deterministic
   scenarios are available, e.g. `LOW_STOCK`, `OUT_OF_STOCK`, `EXPIRY_RISK`,
   `HIGH_TRAFFIC`, `MULTI_CAMERA_JOURNEY`, `SMART_RECEIVING`, `CAMERA_OFFLINE`,
   `COMBINED_CRISIS`.
3. **Activate** a scenario → it mutates only the demo store (guarded by
   `X-Demo-Reset-Key`; real stores are never touched).
4. Watch the dashboards/alerts/insights update.
5. **Reset** from the demo view (or `./scripts/storeye demo-reset`) to return to
   the identical baseline.

## 6. Restart / stop / clean up

```bash
./scripts/storeye restart          # graceful restart of app + DB
./scripts/storeye stop             # stop app + project PostgreSQL
./scripts/storeye stop --keep-db   # stop app only
./scripts/storeye doctor           # environment readiness check anytime
```

## 7. UI / browser notes

- The frontend reads `VITE_API_URL` (default `http://localhost:8000`) at build
  time; `npx tsc -b && npx vitest run && npm run build` re-verifies.
- `ERROR` states show the M22 error boundary (Try again / Reload).
- There is **no backend authentication** (documented limitation): the demo
  account is a UI-level login only. See `docs/privacy_architecture.md`.

## 8. Troubleshooting hiccups

| Symptom | Fix |
|---------|-----|
| `role "ayush" does not exist` | always connect as `storeye`: `-U storeye`, `DATABASE_URL=postgresql+psycopg2://storeye@localhost:5433/storeye` |
| backend won't start (strict) | `./scripts/storeye doctor`; check `DATABASE_URL`, PG running, `alembic check` |
| no camera insights | cameras are demo/synthetic by default; activate a scenario; real sources = `docs/camera_setup.md` |
| `libzbar` errors | `brew install zbar` (macOS) / `apt-get install libzbar0` (Debian) |
| port 8000/5173 busy | `./scripts/storeye stop --clean-orphans` then restart |

Full symptom→fix reference: `docs/troubleshooting.md`.