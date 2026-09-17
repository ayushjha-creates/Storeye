# Storeye — Final Demo Checklist

Use this before any live demo. Total pre-flight time: ~5 minutes.

## A. Pre-flight (before the audience arrives)

### 1. Database
```bash
export DATABASE_URL="postgresql+psycopg2://storeye@localhost:5433/storeye"
cd backend
./.venv/bin/python -m alembic upgrade head       # apply any pending migrations
./.venv/bin/python -m alembic check              # expect: No new upgrade operations detected.
./.venv/bin/python -m scripts.integrity_check     # expect: status OK, exit 0
```
- [ ] `alembic check` clean
- [ ] integrity check OK

### 2. Reset to a known baseline
```bash
DATABASE_URL="postgresql+psycopg2://storeye@localhost:5433/storeye" \
  ./.venv/bin/python -m scripts.seed_demo --reset
```
- [ ] Seed reports **22 insights / 8 alerts / 5 insight alerts / 234 observations**

### 3. Start backend (strict, so any problem is obvious)
```bash
export DATABASE_URL="postgresql+psycopg2://storeye@localhost:5433/storeye"
export ENVIRONMENT=production          # fail-fast startup
cd backend && ./.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```
- [ ] Startup log shows `Startup checks | ... db_reachable=True ... migration_current=True`

### 4. Start frontend
```bash
cd frontend && npm run dev            # http://localhost:5173  (demo login: demo@storeye.local / StoreyeDemo@123)
```
- [ ] Dashboard loads; "Demo store" badge visible in the topbar

### 5. Readiness probes
```bash
curl -s localhost:8000/api/health
curl -s localhost:8000/api/system/status | python -m json.tool   # status: OK
curl -s localhost:8000/api/ready
```
- [ ] `/api/system/status` → `"status": "OK"`, `"database": {"reachable": true, "migration_current": true}`
- [ ] `/api/ready` → `200`

### 6. Demo engine sanity
```bash
KEY="${DEMO_RESET_KEY:-storeye-demo-reset}"
curl -s localhost:8000/api/demo/status
curl -s -X POST -H "X-Demo-Reset-Key: $KEY" localhost:8000/api/demo/reset   # baseline
```
- [ ] `/api/demo/scenarios` lists 12 scenarios
- [ ] reset returns `active_key: "NORMAL_STORE"`

## B. Demo flow (the 5-minute showcase)

Start at **Demo Control Center** (`/app/demo`). The **Presentation view**
(`/app/demo/presentation`) is the guided hub with deep links.

| Step | Screen | Scenario to activate | Show |
|------|--------|----------------------|------|
| 1 | Demo Control | `NORMAL_STORE` | Healthy baseline: no critical alerts |
| 2 | Dashboard | `LOW_STOCK` | Low-stock insights + recommended action |
| 3 | Insights | `OUT_OF_STOCK` | Out-of-stock insight + alert |
| 4 | Insights | `EXPIRY_RISK` | Expiry-risk batch insight |
| 5 | Shelf Intelligence | `LOW_SHELF_BACKSTOCK` | Shelf looks empty while stock exists |
| 6 | Product Intelligence | `MISPLACEMENT` | Product in the wrong zone |
| 7 | Insights | `HIGH_TRAFFIC` | Customer-flow insight |
| 8 | Insights | `HIGH_DWELL` | High-dwell zone insight |
| 9 | Journeys | `MULTI_CAMERA_JOURNEY` | Anonymous cross-camera journey |
| 10 | Cameras / Alerts | `CAMERA_OFFLINE` | Camera-offline alert (no flood) |
| 11 | Smart Receiving | `SMART_RECEIVING` | Human-confirmed OCR batch intake |
| 12 | Demo Control | `COMBINED_CRISIS` | Everything wrong at once |

Finish with **Reset to normal** (`POST /api/demo/reset`).

## C. Points to state while demoing

- [ ] **Offline-first:** pull the network → the app keeps working; internet loss
      is advisory, not an error.
- [ ] **Privacy:** anonymous track ids only; no faces, no embeddings persisted.
- [ ] **Human-in-the-loop:** Smart Receiving requires explicit confirmation.
- [ ] **Deterministic:** the same scenario always produces the same insights.
- [ ] **Real data path:** scenario data is written through real services into
      PostgreSQL — no frontend mock data.

## D. Recovery

| Symptom | Action |
|---------|--------|
| Scenario looks stale | `POST /api/demo/reset` then re-activate |
| `/api/system/status` degraded | `alembic upgrade head`; restart backend |
| Integrity warning | `python -m scripts.integrity_check --json`; do not present until investigated |
| UI page blank | ErrorBoundary shows a recovery card — use **Try again** / **Reload** |
| Backend refuses to start | It is strict: read the logged startup notice (config/DB/migration) |
