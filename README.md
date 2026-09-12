# EdgeRetail-IQ

Privacy-first, offline-first Edge AI retail intelligence platform for Indian
small-format retailers.

Reconciliation-first, not vision-first. Computer vision provides observations;
the decision pipeline is the product.

## Status

- **Milestones 0–11 — Core platform (COMPLETE)**
  - FastAPI domain API over PostgreSQL (source of truth), Alembic migrations
  - Full 15-entity domain, inventory/batch/reconciliation/observation services
- **Milestones 13–17 — Edge AI, intelligence & alerts (COMPLETE)**
  - YOLO-pipeline ingest, camera calibration/regions, product + shelf
    intelligence digests, alert inbox, Smart Batch Receiving (close-up OCR)
  - Backend suite: **221 tests passing** — see `docs/backend_test_database.md`
- **Milestone 12 + 18 — Frontend & demo showcase (COMPLETE)**
  - React 18 + Vite + TS + Tailwind; edge-first UI, Live Store & Reports pages,
    enterprise light theme (navy `brand`, gold accent, dependency-free charts)
  - Deterministic demo dataset (`python -m scripts.seed_demo`, reset via
    `POST /api/demo/reset` with `X-Demo-Reset-Key`) — demo account
    `demo@storeye.local` / `StoreyeDemo@123`
  - Frontend tests: **78 tests passing**; `tsc -b && vite build` clean

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
./scripts/run-tests.sh
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
