# EdgeRetail-IQ

Privacy-first, offline-first Edge AI retail intelligence platform for Indian
small-format retailers.

Reconciliation-first, not vision-first. Computer vision provides observations;
the decision pipeline is the product.

## Status

**Milestones M0–M22 — COMPLETE.** Production-hardened, offline-first edge
platform.

- **M0–M11 — Core platform:** FastAPI domain API over PostgreSQL (source of
  truth), Alembic migrations, full domain + inventory/batch/reconciliation/
  observation services.
- **M13–M17 — Edge AI, intelligence & alerts:** YOLO ingest, camera
  calibration/regions, product + shelf intelligence, alert inbox, Smart Batch
  Receiving (close-up OCR, human-confirmed).
- **M12 + M18 — Frontend & demo showcase:** React 18 + Vite + TS + Tailwind;
  edge-first UI with a dependency-free chart layer.
- **M19 — Anonymous journeys:** privacy-preserving cross-camera continuity
  (in-memory Re-ID; no embeddings persisted).
- **M20 — Store intelligence:** deterministic, evidence-backed insights that
  feed the single alert system.
- **M21 — Demo & scenario engine:** 12 deterministic scenarios over the demo
  store, with a guided presentation view.
- **M22 — Production hardening:** configuration validation, a strict
  config → PostgreSQL → migration-head startup sequence, `GET /api/system/status`
  readiness, a read-only integrity-check service + CLI, and a UI error boundary.

### Verification

- **Backend:** 358 tests passing (PostgreSQL); `alembic check` clean
  (`19c835a1a344`). See `docs/backend_test_database.md`.
- **Frontend:** 119 tests passing; `tsc -b` and `vite build` clean.
- **Docs:** `docs/milestone_22_final_report.md`,
  `docs/final_architecture.md`, `docs/deployment.md`,
  `docs/privacy_architecture.md`, `docs/milestone_22_integration_audit.md`,
  `docs/final_demo_checklist.md`.

Deterministic demo dataset (`python -m scripts.seed_demo`, reset via
`POST /api/demo/reset` with `X-Demo-Reset-Key`) — demo account
`demo@storeye.local` / `StoreyeDemo@123`.

## Architecture

```
Camera → Edge Inference → Temporal Filter → Reconciliation →
Business Impact → Priority Engine → Recommendation → Human Confirmation →
Staff Action → Outcome Measurement → Effectiveness Score
```

The **entire system runs on the edge** (EDGE ONLINE + INTERNET OFFLINE is the
normal state). There is no cloud. Postgres → FastAPI → local web frontend.
See `docs/` for architecture, phases, and roadmap.

## Tech Stack

- **Backend:** Python 3.10+, FastAPI, SQLAlchemy 2.0, PostgreSQL 18
- **Frontend:** React 18, Vite 5, TypeScript (strict), Tailwind CSS, Vitest + Testing Library
- **Vision:** Ultralytics YOLO, OpenCV (Milestone 1+, pipeline in `backend/app/cv`)
- **Cloud:** *None.* Decided against Supabase/cloud streaming — edge-first by design

## Directory Structure

```
backend/     FastAPI application (apps, services, cv, reconciliation, sync)
frontend/    React + Vite + Tailwind
models/      Vision model weights
data/        demo fixtures, videos, imports
docs/        Architecture + roadmap
scripts/     start/test helpers
docker/      (optional, later)
```

## Quickstart

One command installs and runs the whole edge platform (PostgreSQL 18 local
cluster, FastAPI backend, React frontend, local AI):

```bash
cp .env.example backend/.env
./scripts/setup.sh                     # deps + PostgreSQL + migrations + model check
./scripts/storeye start                # backend :8000 + frontend :5173
./scripts/storeye seed                 # deterministic demo dataset
```

- Dashboard: <http://localhost:5173> (login `demo@storeye.local` / `StoreyeDemo@123`)
- API health: <http://localhost:8000/api/health> · status: <http://localhost:8000/api/system/status>
- Day-2 ops: `./scripts/storeye {status|doctor|demo-reset|backup|restore|migrate|restart|stop|logs|models}`
- Guides: `docs/quickstart_demo.md` (showcase) · `docs/quickstart_edge.md` (offline edge install) ·
  `docs/model_assets.md` · `docs/camera_setup.md` · `docs/backup_restore.md` · `docs/update_rollback.md` ·
  `docs/troubleshooting.md` · `docs/deployment.md`

## Run Backend

```bash
export DATABASE_URL="postgresql+psycopg2://storeye@localhost:5433/storeye"
./scripts/start-backend.sh
# or manually
source backend/.venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check: <http://localhost:8000/api/health>

## Run Frontend

```bash
./scripts/start-frontend.sh
# or manually
cd frontend && npm install && npm run dev
```

Dashboard: <http://localhost:5173>

## Run Tests

```bash
./scripts/storeye test        # backend (pytest on storeye_test) + frontend (tsc+vitest+build)
```

## Non-Negotiable Principles

1. **Offline first** — the operational loop never requires internet.
2. **Privacy first** — anonymous tracker IDs only; no face recognition; no
   raw video persisted.
3. **Human-in-the-loop** — the system recommends, humans confirm.
4. **PostgreSQL is the source of truth** (accessed only through the FastAPI service layer).
5. **UUIDs** on every syncable entity.
6. **Edge-first** — EDGE ONLINE + INTERNET OFFLINE is the normal state.
7. **Idempotent sync** — UUID upsert.
8. **Edge → Cloud** only, no operational write-back (current scope).
9. **UTC timestamps.**
10. **Model swappability** — configurable, no code rewrite.
