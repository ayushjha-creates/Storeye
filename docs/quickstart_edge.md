# Storeye — Quickstart (Edge Deployment)

Guide for installing Storeye as a production, offline-first edge node: one
machine, local PostgreSQL, local AI, LAN-only access. The operating state is
**EDGE ONLINE + INTERNET OFFLINE**.

Verified on: **macOS 26.5.1 (arm64)** · Python 3.9.6 · Node 24 · npm 11 ·
PostgreSQL 18.6 (project-local cluster, port 5433). **Windows is not claimed.**

---

## 1. One node, one repo

```
[cameras] ──▶ Edge node (this repo)
                ├─ PostgreSQL  .pgdata/     (business data; port 5433)
                ├─ FastAPI     :8000         (API + embedded AI runtime)
                ├─ React       :5173 / dist  (browser UI on the LAN)
                ├─ models/                   (local AI weights)
                └─ logs/                     (runtime logs)
```

There is **no cloud dependency**. All AI runs locally; raw video is never stored.

## 2. Fresh-machine install (internet available — STATE A)

```bash
# system packages (macOS)
brew install postgresql@18 zbar            # or your OS equivalents

cp .env.example backend/.env
./scripts/setup.sh                         # idempotent bootstrap
./scripts/storeye models                   # model-asset validation (no downloads)

# optional: stage Re-ID + OCR weights now (internet only during bootstrap)
#   → docs/model_assets.md §2
```

## 3. Fully-offline edge node (STATE B)

The runtime never needs the internet — only the **initial** staging does.
Copy the repo + the cached weight dirs (`~/.cache/torch/...`,
`~/.paddlex/official_models/...`) and system packages to the target machine;
then the same `scripts/setup.sh` runs without downloading anything.
**STATE C (fresh machine, zero internet, no staging) is NOT supported.** See
`docs/model_assets.md` for the offline recipe.

## 4. Production configuration

Edit `backend/.env` (created from `.env.example`):

```bash
ENVIRONMENT=production          # ⇒ strict startup (fails loudly on bad DB/config)
STRICT_STARTUP=true             # belt-and-braces
DEBUG=false
DEMO_MODE=false                 # disable the demo API entirely unless you want it
DEMO_RESET_KEY=<unique,secret> # and set the same value as VITE_DEMO_RESET_KEY
CORS_ORIGINS=["http://<edge-lan-ip>:5173"]
```

Every value is validated by `backend/app/core/config.py` (M22); a bad value
aborts startup before the app serves traffic.

## 5. Day-2 operations (one-command)

```bash
./scripts/storeye setup            # idempotent bootstrap (also fixes a broken node)
./scripts/storeye migrate          # alembic upgrade head + drift check
./scripts/storeye start            # PostgreSQL + backend + frontend (background)
./scripts/storeye status           # per-component health + URLs
./scripts/storeye restart          # graceful recycle
./scripts/storeye stop             # graceful stop (app + project PostgreSQL)
./scripts/storeye stop --clean-orphans  # also kill untracked uvicorn/vite
./scripts/storeye doctor           # full readiness report (--json for scripts)
./scripts/storeye models           # validate model assets (never downloads)
./scripts/storeye backup           # pg_dump → backups/  (--all for both DBs)
./scripts/storeye restore backups/storeye-<ts>.dump --yes
./scripts/storeye logs backend     # tail backend log (frontend|postgres too)
```

Process management uses pid files under `logs/run/`; `stop` signals only
processes whose command matches our known patterns (never unrelated services).

## 6. Logs and data separation

| Path | Git-ignored | Contents |
|------|-------------|----------|
| `logs/backend/` | yes | uvicorn + PostgreSQL logs, backend.pid |
| `logs/ai/` | yes | reserved for AI-runtime logs (AI logs with the backend today) |
| `logs/frontend/` | yes | vite dev logs, frontend.pid |
| `data/` | yes | demo fixtures, videos, imports |
| `.pgdata/` | yes | project-local PostgreSQL cluster |
| `backups/` | yes | pg_dump archives |

Logs never contain secrets, embeddings, or raw images (see
`docs/privacy_architecture.md`). Rotate via your OS (`logrotate`/`newsyslog`).

## 7. Backup / restore / update

- **Backup:** `./scripts/storeye backup` (custom-format `pg_dump`). PostgreSQL
  is the source of truth.
- **Restore:** `./scripts/storeye restore <file> --yes` (destructive; drops and
  recreates the target DB).
- **Update:** pull the new version, run `./scripts/storeye migrate`, restart.
  Full flow + rollback in `docs/update_rollback.md`.

## 8. Security posture (read once)

- **No built-in authentication.** Trusted single-tenant edge node: bind to the
  LAN only, or front with a reverse proxy (TLS + auth) and set `CORS_ORIGINS`.
- Keep `backend/.env` secret and git-ignored; never commit `.env`.
- Never expose PostgreSQL ports beyond the trusted LAN.
- OpenVINO/provider choice and Re-ID toggles: `REID_PROVIDER`, `REID_ENABLED`
  (anonymous embeddings only — no faces, no biometrics).

## 9. Verification of a fresh deployment

```bash
./scripts/storeye status                     # all components healthy
./scripts/storeye doctor --api-url http://localhost:8000 \
    --frontend-url http://localhost:5173     # result READY
curl http://localhost:8000/api/system/status # status OK, migration_current true
./scripts/storeye test                       # full backend + frontend suite
```

See `docs/deployment.md` (extended reference) and `docs/troubleshooting` in
`docs/milestone_23_deployment_packaging.md`.