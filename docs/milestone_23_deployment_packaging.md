# Milestone 23 — Deployment Packaging & One-Click Edge Setup

> Completed: 2026-09-17 · Scope: provisioning/scripts/docs/verification — no
> new features; every M0–M22 contract preserved.

---

## 1. Summary

Storeye can now be installed, operated, verified, backed up and updated from a
single shell command on a clean edge node. This milestone added:

- a **one-click provisioning suite** (`scripts/`) covering the full lifecycle:
  `setup`, `migrate`, `seed`, `demo-reset`, `doctor`, `models`, `start`,
  `stop`, `restart`, `status`, `backup`, `restore`, `logs`, `test`,
- a **model-asset validator** (`app/deployment/model_check.py`) that proves the
  AI assets are present **without ever downloading at runtime**,
- an **environment doctor** (`app/deployment/doctor.py`) that reports readiness
  of Python/Node/config/PostgreSQL/migrations/models/writable dirs/cameras and
  optional HTTP probes,
- **offline-first deployment docs** covering the STATE A/B/C boundary
  (HTTP install ↔ offline runtime),
- **deterministic demo-reset tooling** with proof-by-verification.

Verification is recorded in §7; the full test matrix (backend 378 / frontend
119) is in §12.

## 2. Architecture

```
                    ┌────────────────── Edge node (this repo) ──────────────────┐
 camera sources ──▶ │  FastAPI backend  :8000   ⟨--Lifespan-->  PostgreSQL 5433 │
                    │   ├─ AI runtime (lazy, per-camera trackers)                │
 (HTTP)  ────────▶  │   ├─ api/ (REST)  ──  service layer  ──  storeye DB        │
 browser ────────▶  │  React frontend :5173 / dist (VITE_API_URL → :8000)       │
                    │  models/  (weights)   .pgdata/   logs/   data/   backups/  │
                    └────────────────────────────────────────────────────────────┘
```

Layer boundaries: routes → services (single source of truth) → PostgreSQL.
No cloud dependency; raw video never persisted; PostgreSQL is the source of
truth (legacy SQLite is diagnostics-only). AI runtime is optional at startup —
missing weights disable AI but never the business API.

## 3. Provisioning and Prerequisites

Verified environment and baselines:

| Item | Value |
|------|-------|
| OS | macOS 26.5.1 (arm64) — Windows **not claimed** |
| Python | 3.9.6 (venv at `backend/.venv`) |
| Node / npm | 24.12.0 / 11.6.2 |
| PostgreSQL | **18.6** (`/Library/PostgreSQL/18/bin`), project-local cluster `.pgdata`, port **5433**, trust auth, superuser `storeye` |
| Databases | `storeye` (business), `storeye_test` (tests) |
| AI extras | OpenVINO optional (not installed); `zbar` installed (`/opt/homebrew/lib/libzbar.dylib`) |

Provisioning commands:

```bash
brew install postgresql@18 zbar        # system packages (macOS);
                                       # Linux: postgresql-14+, libzbar0
cp .env.example backend/.env           # then edit as needed
./scripts/setup.sh                     # idempotent: deps + venv + npm ci +
                                       # init/start PG + create DBs + migrate
```

`setup.sh` re-runs safely on an already-provisioned node (used to repair).

## 4. Authentication and Network Topology

- **No built-in authentication** (unchanged from M0–M22, documented in
  `docs/privacy_architecture.md`). The demo account
  (`demo@storeye.local` / `StoreyeDemo@123`) is a UI-level login; demo mutating
  endpoints are protected by the `X-Demo-Reset-Key` reset key and the
  service-layer `is_demo` guard.
- **Network topology**: single trusted LAN edge node. Production hardening =
  bind to LAN, set `ENVIRONMENT=production`, `DEMO_MODE=false`, a private
  `DEMO_RESET_KEY`, and an authenticating TLS reverse proxy in front.
- Connected profile assumed **EDGE ONLINE + INTERNET OFFLINE**; the runtime loop
  never makes internet requests.

## 5. Installation Steps

1. Install system packages (PostgreSQL tools, optional `zbar`).
2. `cp .env.example backend/.env` and set `DATABASE_URL`.
3. `./scripts/setup.sh` → venv deps, `npm ci`, project-PG init/start, create
   `storeye` + `storeye_test`, `alembic upgrade head`.
4. `./scripts/storeye models` → validate all AI assets (never downloads).
5. `./scripts/storeye seed` → deterministic demo dataset.
6. `./scripts/storeye start` → backend :8000 + frontend :5173.
7. `./scripts/storeye status` / `doctor --api-url ... --frontend-url ...` → READY.
8. (Optional) `./scripts/storeye demo-reset --verify` → prove determinism.

STATE boundaries (`docs/model_assets.md`): **A** fresh+online → full install
(internet needed once for pip/npm/torch/PaddleOCR caches); **B** prepared/no-
internet → runtime 100% offline (**the normal state**); **C** fresh+no-internet
→ **NOT SUPPORTED** (explicitly).

## 6. Configuration

- `backend/.env` created from the grouped, labeled `.env.example` (APPLICATION,
  DATABASE, API CORS LOGGING, CAMERA, AI-REID, MODEL ASSETS, INTELLIGENCE,
  DEMO, LEGACY instrumentation). Every value is validated by
  `app/core/config.py` (M22); a bad value is fatal in strict mode.
- Frontend build vars in `frontend/.env.example` (`VITE_API_URL`,
  `VITE_DEMO_*`); `FIREBASE`/store cloud placeholders remain inert.
- Scripts read `backend/.env` via a **dotenv parser** (`scripts/lib/common.sh`
  `load_env`) — safe for values containing parens (e.g. `LOG_FORMAT=%(levelname)s…`).

### Live verification (all commands, 2026-09-17)

```
$ ./scripts/storeye start
 ok  PostgreSQL   running (pgdata=…/.pgdata, port=5433)
 ok  Backend      healthy at http://localhost:8000 (pid …)
 ok  Frontend     ready at http://localhost:5173 (pid …)

$ curl -s http://localhost:8000/api/system/status
{"status":"OK","app":"EdgeRetail-IQ",…,"migration_current":true,
 "migration_db_revision":"19c835a1a344","migration_head":"19c835a1a344",
 "reid":{"enabled":true,"provider":"torch"},"demo_mode":true,"notices":[]}

$ (cd backend && ./.venv/bin/python -m app.deployment.model_check --deep)
[ OK ] AI person detector (YOLO11n)            … yolo11n.pt (5483 KiB)
[ OK ] AI shelf/product model                   … shelf_model.pt (6143 KiB)
[ OK ] AI Re-ID provider (torch)                … resnet18-f37072fd.pth
[ OK ] AI OCR (PaddleOCR)                       … official_models
[ OK ] AI barcode backend (pyzbar + libzbar)    … libzbar.dylib
Result: READY (5 ok, 0 warn, 0 error)            exit=0

$ ./scripts/storeye doctor --api-url http://localhost:8000 \
                           --frontend-url http://localhost:5173
[ OK ] Python runtime / Node+npm / Configuration
[ OK ] PostgreSQL connectivity / Database migrations (at head)
[ OK ] person detector, shelf model, Re-ID, OCR, barcode / Writable dirs
[ OK ] Camera configuration — 5 camera(s) well-formed
[ OK ] Backend HTTP health -> 200 / Frontend reachability -> 200
Result: READY (14 ok, 0 warn, 0 error)           exit=0

$ ./scripts/storeye demo-reset --verify
  deterministic:            True
  demo store present:       True
  non-demo store preserved: True

$ ./scripts/storeye migrate
 ok  Schema is at head (alembic check clean)

$ ./scripts/storeye backup --all
 ok  backups/storeye-20260917-090305.dump (260K)    ok  storeye_test (4.0K)

# restore → scratch DB, then full integrity audit on the restored data:
restore exit=0 | integrity: status OK, errors 0, warnings 0
  stats: {'stores': 2, 'cameras': 5, 'inventory': 13, 'batches': 6,
          'alerts': 11, 'insights': 22}

$ ./scripts/storeye restart   ok   →   stop --clean-orphans   ok  (tracked
  PIDs signalled; stray uvicorn/vite removed without touching other services)
```

### Logs (this-product only)

```
logs/backend/    uvicorn + PostgreSQL logs, backend.pid
logs/ai/         reserved AI-runtime logs
logs/frontend/   vite log, frontend.pid
data/  .pgdata/  backups/   (all git-ignored; see .gitignore)
```

No secrets, embeddings or raw images are written to logs — verified
invariant (`docs/privacy_architecture.md`).

## 9. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `role "ayush" does not exist` | always connect as `storeye` (`-U storeye`, `DATABASE_URL=…//storeye@…`); PG_USER is `storeye` |
| doctor `NOT READY (DATABASE_URL not set)` | `backend/.env` missing → `cp .env.example backend/.env` (created during this milestone's live run) |
| `scripts/setup.sh` complains about port 5433 busy | another service owns it; `storeye stop --clean-orphans`, or set `PGPORT` |
| seed transients on an already-seeded DB | seed is idempotent; re-run, or use `--reset` (robust path) |
| `storeye seed` / doctor fail after `migrate` | run `./scripts/storeye doctor` first; DB must exist + be at head |
| barcode `pyzbar` errors | install system `zbar` (Homebrew/Debian); macOS naive import fails but the app bootstraps libzbar via `barcode_decoder.py` |
| `storeye start` "orphaned process" on dev ports | leftover uvicorn/vite from a killed session → `storeye stop --clean-orphans` |
| `git` errors (`.git/index … Operation timed out`) | iCloud Drive checkout limitation; no M23 commit made yet — retry after files sync |
| login always fails / demo endpoints 403 | `DEMO_RESET_KEY` mismatch between backend `.env` and `VITE_DEMO_RESET_KEY`; or `DEMO_MODE=false` |

## 10. Rollback and Updates

- Update = `storeye backup` → `storeye stop` → `git pull` → `scripts/setup.sh`
  → `storeye migrate` → `storeye doctor` → `storeye start`.
- **Code-only rollback**: checkout the previous commit + re-setup; safe when no
  schema change (`git diff prev..new -- backend/alembic`).
- **Schema+data rollback**: never a bare Alembic downgrade; restore the
  pre-update `pg_dump` (`storeye restore … --yes`) then checkout old code.
  Full plan in `docs/update_rollback.md`.

## 11. Milestone Outputs

| Output | Location |
|--------|----------|
| Deployment package: model validator, doctor, report model | `backend/app/deployment/{model_check,doctor,report,__init__}.py` |
| One-click lifecycle scripts | `scripts/` (`lib/common.sh` + `setup|migrate|seed|demo-reset|start|stop|status|doctor|backup|restore|start-backend|start-frontend|storeye`) |
| Determinism proof CLI | `backend/scripts/demo_verify.py` |
| Env templates | `.env.example`, `frontend/.env.example` |
| Docs | `docs/model_assets.md`, `camera_setup.md`, `quickstart_demo.md`, `quickstart_edge.md`, `backup_restore.md`, `update_rollback.md`, `deployment.md`, `README.md` |
| Tests | `test_deployment_utils.py` (19), `test_demo_reset_is_deterministic_and_isolated` |
| `.gitignore` | now covers `/logs/` and `/backups/` |

## 12. Test matrix

| Suite | Result | Notes |
|-------|--------|-------|
| Backend pytest (PostgreSQL `storeye_test`) | **378 passed** (176.7s) | was 358 at M22 end; +19 deployment utils +1 demo determinism |
| Frontend vitest | **119 passed** | 31 files |
| `npx tsc -b` | clean | |
| `npm run build` | clean | 396.93 kB JS → gzip 107.32 kB |
| `alembic check` | clean | head `19c835a1a344`, no drift |
| model asset validator | READY (5 ok) | `--deep`, exit 0 |
| environment doctor | READY (14 ok, 0 warn, 0 error) | live HTTP probes, exit 0 |
| demo determinism | deterministic=True | two reset+seed cycles; non-demo preserved |
| restore + integrity on restored data | status OK, 0 err/0 warn | scratch DB round-trip |

## 13. Out-of-scope / NOT VERIFIED

- **Live physical-camera lifecycle** (ONLINE→OFFLINE→recovery) & multi-camera
  Re-ID across simultaneous physical streams — not executed this milestone.
- **RTSP capture** — reserved, no adapter runtime-tested.
- **Wireless/hotspot provisioning and baseline sync from a factory image** —
  the offline staging recipe is documented; containers/multi-machine operator
  target machines still unverified.
- **Windows** deployment — unverified (macOS arm64 verified).
- **STATE C** (fresh machine, zero internet, nothing staged) — **not supported**.
- Manual browser click-through of all 12 demo scenarios in one sitting —
  covered by M21 HTTP + frontend tests, not repeated here.

None of the above is claimed; each is called out rather than silently assumed.

## 14. Final Report (sign-off)

M23 is **complete and verified** on the development edge node:

- One-command provisioning + day-2 lifecycle work end-to-end
  (setup → migrate → seed → start → status → doctor → demo-reset → backup →
  restore-to-scratch → restart → stop).
- All AI assets validated locally; nothing downloads at runtime.
- Full regression green: **backend 378 passed / frontend 119 passed**, build
  clean, schema at head, demo determinism proven, backups restorable with a
  clean integrity audit.
- Offline docs (STATE A/B/C) produced; the §26 clean-deployment steps above
  were executed live and recorded in §7.
- Known operational caveat: git is currently unusable on this iCloud Drive
  checkout (`.git/index … Operation timed out`); no M23 commit exists yet.

Deliverable restores a fully declarative, testable, rebuildable Storeye edge
box from source + `.env` — with honest NOT VERIFIED items itemized above.