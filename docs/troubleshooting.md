# Storeye — Troubleshooting

Consolidated reference for installing and running Storeye. Work top-down with
the doctor: run `./scripts/storeye doctor` and fix every `[FAIL]` before going
further — it covers Python/Node/config/PostgreSQL/migrations/models, writable
directories and (optionally) live HTTP probes.

---

## 1. Quick triage

| Symptom | First command |
|---------|---------------|
| anything won't install/start | `./scripts/storeye doctor --json` |
| AI models flagged | `./scripts/storeye models` |
| DB schema/migration doubt | `./scripts/storeye migrate` (checks + upgrades) |
| service won't stop / ports busy | `./scripts/storeye stop --clean-orphans` |
| a dump won't restore | `./scripts/storeye restore <file> --yes` then `scripts.integrity_check` |
| "used to work, now broken" after update | `./scripts/storeye doctor` + restore pre-update backup |

## 2. Install / setup issues

| Symptom | Cause / fix |
|---------|-------------|
| `role "ayush" does not exist` | Always connect as the `storeye` superuser: `-U storeye`, `DATABASE_URL=postgresql+psycopg2://storeye@localhost:5433/storeye` |
| `load_env` / `backend/.env: syntax error near '('` | Fixed in M23 — use the current `scripts/lib/common.sh` (dotenv parser). Re-`git pull` if you see this. |
| port **5433 already in use** but project PG not running | Another service owns it; `storeye stop --clean-orphans` won't help — set `PGPORT` (`PGDATA` too) or stop the other service. |
| `setup.sh` re-init fails midway | Idempotent — just re-run it; it resumes PG/create-db/migrate |
| Postgres tools missing | macOS: `brew install postgresql@18`; Debian/Ubuntu: `apt-get install postgresql`; set `STOREYE_PG_BIN` if binaries are elsewhere |
| `alembic check` reports drift | Run `./scripts/storeye migrate`; if still drifting, DB is ahead/behind head — restore a known-good backup first |

## 3. Runtime / backend issues

| Symptom | Cause / fix |
|---------|-------------|
| strict startup abort (`Storeye startup refused`) | `ENVIRONMENT=production` or `STRICT_STARTUP=true` with bad config/DB. Check `backend/.env`, PG up, `alembic check` |
| `/api/system/status` 503 | config invalid or PostgreSQL unreachable |
| `/api/system/status` 200 `DEGRADED` | schema behind head → `./scripts/storeye migrate` |
| backend healthy per `status` but AI disabled | missing model assets → `./scripts/storeye models`; missing `openvino` is fine (optional) |
| doctor says `DATABASE_URL is not set` | `backend/.env` missing → `cp .env.example backend/.env`, then restart components |
| seeds/CLI say schema not found | run migrations first: `./scripts/storeye migrate` |

## 4. Data / seed issues

| Symptom | Cause / fix |
|---------|-------------|
| `storeye seed` transient integrity error on an already-seeded dev DB | seed is idempotent — re-run; or use `--reset` (robust rebuild path) |
| demo store missing / wrong counts | `./scripts/storeye seed` then `./scripts/storeye demo-reset --verify` (deterministic guard) |
| demo endpoints 403/denied | `DEMO_RESET_KEY` mismatch between `backend/.env` and frontend `VITE_DEMO_RESET_KEY`; or `DEMO_MODE=false` |
| restore fails with owner errors | invoke via `./scripts/storeye restore … --yes` (uses `--no-owner --no-privileges`) |
| integrity check finds orphans/negatives | data drift; restore the closest good backup and re-verify (`scripts.integrity_check`) |

## 5. Frontend issues

| Symptom | Cause / fix |
|---------|-------------|
| UI can't reach API | `VITE_API_URL` baked at build time; rebuild after changing it. Cross-origin → add origin to `CORS_ORIGINS` |
| login always fails | No backend auth exists — demo login is UI-level; ensure backend `/api/health` is 200 |
| blank page / error boundary | open browser console; use **Try again** / reload. Dev: `npm run dev` in `frontend/` |
| demo view won't reset | check `X-Demo-Reset-Key` equals `backend Settings.DEMO_RESET_KEY` |

## 6. AI / model issues

| Symptom | Cause / fix |
|---------|-------------|
| `model_check` shows missing `.pt` | assets ship in the repo (`models/yolo/yolo11n.pt`, `models/shelf/shelf_model.pt`); re-clone with LFS/all branches if pointers (<64 KiB) |
| Re-ID missing weights | `REID_TORCH_WEIGHTS_PATH` → fetch once (see `docs/model_assets.md` §2), or set `REID_PROVIDER=stub` for tests/demo |
| `pyzbar` import error (macOS) | install system `zbar` (`brew install zbar`); the app bootstraps `libzbar` via `barcode_decoder.py`, naive import can still fail in isolation |
| PaddleOCR slow first predict | official models auto-cache under `~/.paddlex/official_models` during first (online) use — that is bootstrap, not runtime |

## 7. Process / port issues

| Symptom | Cause / fix |
|---------|-------------|
| `storeye stop` labels running services "orphans" | stale `scripts/` — update; current `stop.sh` handles tracked pid-files first, sweeps leftovers after |
| leftover `uvicorn`/`vite` survive a killed session | `./scripts/storeye stop --clean-orphans` (kills only our known patterns) |
| `storeye start` hangs waiting for health | check `logs/backend/` + `logs/frontend/` for the real error; often a stale DB or wrong `.env` |

## 8. Git / filesystem quirks (known)

| Symptom | Cause / fix |
|---------|-------------|
| `git: .git/index: unable to map index file: Operation timed out` | iCloud Drive evicted `.git/index` (dataless). Fix: `rm .git/index && git reset` (index is rebuilt from HEAD; objects are local) |
| `git status` slow on this checkout | iCloud; run git from a non-Cloud folder or after `brctl download` of `.git` |

## 9. Still stuck?

1. `./scripts/storeye doctor --json` and include the `overall` result.
2. Read the exact component log: `./scripts/storeye logs backend|frontend|postgres`.
3. Confirm schema state: `./scripts/storeye migrate` and `/api/system/status`.
4. Reference `docs/milestone_23_deployment_packaging.md` §9 and per-topic guides:
   `quickstart_demo.md` · `quickstart_edge.md` · `model_assets.md` ·
   `camera_setup.md` · `backup_restore.md` · `update_rollback.md`.