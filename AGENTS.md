# Status Summary

## Objective
- **M25 — Mobile-to-Edge USB Intake Bridge** (IN PROGRESS — M25 backend+frontend
  complete; §39 final response given below; git commit/push still pending user
  decision). Phone = camera, laptop = edge computer: a watcher polls a USB
  intake folder, validates + sha256-de-duplicates files, and runs each new
  package photo through the EXISTING M17 pipeline (pyzbar → PaddleOCR →
  ExpiryParser → catalog) with NO new AI / cloud / images-in-PostgreSQL.
  Human review + M17 confirm stay the only mutation path. Must preserve every
  M0–M24 contract (M24 does not exist in this line; M23 is the base).

## Current State
**M23 core DONE — backend 378 passed / frontend 119 passed, tooling live-tested:**
- `backend/app/deployment/`: `report.py` (Check/CheckReport; PASS/WARN/ERROR/SKIP;
  overall READY/DEGRADED/NOT READY; exit 0 = no ERROR), `model_check.py`
  (`python -m app.deployment.model_check [--json] [--deep]` from `backend/`),
  `doctor.py` (`python -m app.deployment.doctor [--json] [--no-db] [--fast]
  [--api-url] [--frontend-url]`). Verified: model_check --deep → READY 5 ok;
  doctor full deep → READY 12 ok.
- `scripts/` one-click suite (all `bash -n` clean + live-tested end-to-end
  incl. starting/stopping the project PostgreSQL cluster): `lib/common.sh`,
  `setup.sh`, `migrate.sh`, `seed.sh`, `demo-reset.sh` (`--verify`),
  `start.sh`, `stop.sh` (`--clean-orphans`, `--keep-db`), `status.sh`,
  `doctor.sh`, `backup.sh` (pg_dump custom → `backups/`), `restore.sh`
  (destructive; `--yes` required), `start-backend.sh`, `start-frontend.sh`,
  `storeye` dispatcher (setup/migrate/seed/demo-reset/doctor/models/start/stop/
  restart/status/backup/restore/logs/test/help). Fixed historical
  `cd scripts/backend` path bug in start-backend/start-frontend.
- `backend/scripts/demo_verify.py`: deterministic-reset proof (two reset+seed
  cycles → identical counts; non-demo store preserved).
- Env templates: root `.env.example` (grouped + labeled) and `frontend/.env.example`.
- New tests: `test_deployment_utils.py` (19, `no_db`); added
  `test_demo_reset_is_deterministic_and_isolated` to `test_demo_api.py` (11 pg).
  Full suite **378 passed** (was 358). Frontend unchanged gates: `npx tsc -b`
  clean, **119 vitest passed**, `npm run build` green (107.32 kB gzip JS).
  `alembic check` clean at head `19c835a1a344`.
- Live runs: `storeye start` → backend pid + frontend pid healthy; `--clean-orphans`
  removed a stray uvicorn (80027) + vite (18801); `demo-reset --verify` →
  deterministic True; `backup --all` → backups/storeye-20260917-085140.dump;
  integrity_check on dev DB → OK, 0 errors/warnings.
- Docs: new `docs/model_assets.md`, `camera_setup.md`, `quickstart_demo.md`,
  `quickstart_edge.md`, `backup_restore.md`, `update_rollback.md`,
  `troubleshooting.md`,
  `docs/milestone_23_deployment_packaging.md` (§36 report: summary, architecture,
  provisioning, network topology, install, configuration, verification logs,
  logs, troubleshooting, rollback, outputs, test matrix, NOT VERIFIED);
  `docs/deployment.md` + README reworked (one-click quickstart, scripts table,
  process/log/backups layout). `.gitignore` now covers `/logs/` and `/backups/`.
- Fixes made this session: `load_env` in `scripts/lib/common.sh` now parses
  dotenv lines instead of `source` (values containing parens like
  `LOG_FORMAT=%(levelname)-8s …` crashed bash); `stop.sh` now tries tracked
  pid-files BEFORE `--clean-orphans` port sweeps (previously the running
  services were labelled "orphans"). `backend/.env` was created from the
  example (git-ignored).

## Important Notes
- **DB URLs**: always `DATABASE_URL="postgresql+psycopg2://storeye@localhost:5433/storeye"` for alembic/seed/integrity CLI; tests use `TEST_DATABASE_URL` → `storeye_test`.
- **Startup probes under pytest**: `assess_runtime()`/`run_startup_checks()` skip the PostgreSQL probe when `"pytest" in sys.modules` (or `probe_database=False`). `/api/system/status` calls `skip_in_tests=False` and does probe the configured `DATABASE_URL`.
- **init_engine gotcha**: `app/db/session.py:43` is a once-guarded singleton — first caller in a pytest session wins. Edge tests must `dispose_engine()` + `init_engine(TEST_DB_URL)` in their `client` fixture or the worker writes to prod storeye (FK violations).
- **Shelf clock gotcha**: M15 shelf intelligence bounds its observation window with wall-clock `datetime.now()` (not the passed `now`). Scenario/test clocks must be near the wall clock (`NOW = datetime.now(timezone.utc) - timedelta(minutes=1)`) or shelf-derived insights won't appear.
- **M23 gotchas**: doctor must use `session.execute(select(Camera)).scalars().all()` (not Session.exec); demo cameras have semantic `config.kind` and no source path → exempt from doctor's source-path warning; model validator min file size 64 KiB (Git-LFS stub guard) and must NEVER auto-download (STATE A/B/C boundary); `scripts` run under `set -euo pipefail` → `port_pid ... || true`; naive `pyzbar` import fails on macOS though `barcode_decoder.py` bootstraps `find_library` fine; `openvino` is optional (not installed); seed without `--reset` can transiently error on an already-seeded dev DB (re-run is fine, `--reset` path is robust); `pytest.ini` marker line has a cosmetic `opt-in)filterwarnings =` run-on (harmless).
- **Frontend gotchas**: `Stat` counts up numeric values via rAF (never advances in jsdom) → assert labels/hints/string durations only; `stubFetchRoutes` matches URL substrings (list specific routes like `/activate` first); `getByText` is exact full-text match (use regex); use `getAllByText` for repeated labels. `Button` forwards `aria-label` (M21); it does NOT forward arbitrary props. `ErrorBoundary` swallows child render errors — restore `console.error` spy in tests.
- `frontend/src/config/demo.ts` `resetKey` defaults to `storeye-demo-reset` (matches backend `Settings.DEMO_RESET_KEY` default); override via `VITE_DEMO_RESET_KEY`.
- No auth system exists; demo mutating endpoints rely on the reset key + service-layer `is_demo` guard (documented limitation in `docs/privacy_architecture.md`).
- Test markers: `pg`, `no_db`, `real_ai`. Camera `config.kind` must be `usb`/`file`/`rtsp`. EdgeRuntime `reid_enabled=None` override (edge tests use `reid_enabled=False`).
- Legacy SQLite stack (`app/core/database.py`) is diagnostics-only (health/ready/metrics); never a business fallback. `DATABASE_URL` validation rejects `sqlite://`.
- Main `frontend/` gates: `npx tsc -b && npx vitest run && npm run build`. `storeye-frontend/` is separate, NOT in git — don't restore.
- Git: origin `https://github.com/ayushjha-creates/Storeye.git`, branch `main`. NOTE: currently `git` fails with `.git/index: unable to map index file: Operation timed out` (iCloud Drive filesystem) — plan for commits accordingly; no M23 commit has been made yet.

## Next Move
- M23 is functionally complete: §36 report written, full regression re-run
  today (378/378 backend, 119/119 frontend), live clean-deployment battery
  executed (start→status→system/status→model_check→doctor→migrate→
  demo-reset --verify→backup→restore-to-scratch+integrity→restart→stop).
  Deliver the §37 final response. Optionally retry `git add/commit` once the
  `.git/index` iCloud timeout clears (no M23 commit exists yet).