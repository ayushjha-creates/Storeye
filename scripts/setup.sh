#!/usr/bin/env bash
# ============================================================================
# Storeye — one-click edge setup.
#
# Idempotent: safe to re-run. Performs, in order:
#   1. prerequisite checks            (python3, node/npm, PostgreSQL tools)
#   2. backend virtualenv + deps
#   3. frontend deps                  (unless --skip-frontend / no node)
#   4. backend/.env + frontend/.env   (from the *.env.example templates)
#   5. project-local PostgreSQL       (init + start; port 5433)
#   6. databases: storeye, storeye_test
#   7. Alembic migrations
#   8. model-asset validation         (no downloads)
#   9. environment doctor
#
# Nothing is downloaded if the machine is already provisioned. Model weights
# and PaddleOCR official models are fetched on bootstrap (see docs/model_assets.md).
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

SKIP_FRONTEND=0
SKIP_MODELS=0
SKIP_DOCTOR=0
FORCE=0

usage() {
  cat <<'EOF'
Usage: scripts/setup.sh [options]

Options:
  --skip-frontend   do not install/build frontend dependencies
  --skip-models     skip the AI model-asset validation step
  --no-doctor       skip the final environment doctor
  --force           reinstall Python/npm dependencies even if present
  -h, --help        show this help
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --skip-frontend) SKIP_FRONTEND=1 ;;
    --skip-models)   SKIP_MODELS=1 ;;
    --no-doctor)     SKIP_DOCTOR=1 ;;
    --force)         FORCE=1 ;;
    -h|--help)       usage; exit 0 ;;
    *) die "Unknown option: $1 (see --help)" ;;
  esac
  shift
done

printf "\n${_C_BOLD}Storeye setup${_C_RESET} — repo: %s\n\n" "$PROJECT_ROOT"

# -- 1. prerequisites --------------------------------------------------------
log "Checking prerequisites"
have python3 || die "python3 not found. Install Python 3.9+ and re-run."
PY_VER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
ok "python3 $PY_VER"

if have node && have npm; then
  ok "node $(node --version), npm $(npm --version)"
  HAVE_NODE=1
else
  warn "node/npm not found — frontend will not be installed (backend-only setup)."
  HAVE_NODE=0
fi

if pg_tools_available; then
  ok "PostgreSQL tools: $PG_BIN"
else
  warn "PostgreSQL tools not found in common locations."
fi

# -- 2. backend deps ---------------------------------------------------------
ensure_venv
PY="$(venv_python)"
if [ "$FORCE" = "1" ] || ! "$PY" -c "import fastapi" >/dev/null 2>&1; then
  log "Installing backend Python dependencies"
  "$VENV_DIR/bin/pip" install --upgrade pip -q
  "$VENV_DIR/bin/pip" install -r "$BACKEND_DIR/requirements.txt" -q
  "$VENV_DIR/bin/pip" install -r "$BACKEND_DIR/requirements-dev.txt" -q
  ok "Backend dependencies installed"
else
  ok "Backend dependencies present"
fi

# -- 3. frontend deps --------------------------------------------------------
if [ "$SKIP_FRONTEND" = "1" ]; then
  warn "Skipping frontend dependencies (--skip-frontend)"
elif [ "$HAVE_NODE" = "1" ]; then
  if [ "$FORCE" = "1" ] || [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    log "Installing frontend dependencies"
    if [ -f "$FRONTEND_DIR/package-lock.json" ]; then
      ( cd "$FRONTEND_DIR" && npm ci --no-audit --no-fund )
    else
      ( cd "$FRONTEND_DIR" && npm install --no-audit --no-fund )
    fi
    ok "Frontend dependencies installed"
  else
    ok "Frontend dependencies present"
  fi
fi

# -- 4. env files ------------------------------------------------------------
if [ ! -f "$BACKEND_DIR/.env" ]; then
  cp "$PROJECT_ROOT/.env.example" "$BACKEND_DIR/.env"
  ok "Created backend/.env from .env.example"
else
  ok "backend/.env already exists (left untouched)"
fi
if [ "$HAVE_NODE" = "1" ] && [ ! -f "$FRONTEND_DIR/.env" ]; then
  cp "$FRONTEND_DIR/.env.example" "$FRONTEND_DIR/.env"
  ok "Created frontend/.env from .env.example"
fi

load_env
ensure_dirs

# -- 5/6. PostgreSQL + databases --------------------------------------------
ensure_postgres
ensure_database "$DB_NAME"
ensure_database "$TEST_DB_NAME"

# -- 7. migrations -----------------------------------------------------------
export DATABASE_URL="${DATABASE_URL:-$(derive_db_url)}"
log "Applying database migrations"
( cd "$BACKEND_DIR" && "$VENV_DIR/bin/alembic" upgrade head ) \
  || die "Alembic migration failed. Check DATABASE_URL ($DATABASE_URL)."
ok "Migrations at head"

# -- 8. model assets ---------------------------------------------------------
if [ "$SKIP_MODELS" = "1" ]; then
  warn "Skipping model-asset validation (--skip-models)"
else
  log "Validating local AI model assets (no downloads)"
  if ( cd "$BACKEND_DIR" && "$PY" -m app.deployment.model_check ); then
    ok "Model assets ready"
  else
    warn "Some model assets are missing — the app can still start, but AI"
    warn "features may degrade. See docs/model_assets.md, then re-run:"
    warn "  (cd backend && ./.venv/bin/python -m app.deployment.model_check --deep)"
  fi
fi

# -- 9. doctor ---------------------------------------------------------------
if [ "$SKIP_DOCTOR" = "1" ]; then
  warn "Skipping environment doctor (--no-doctor)"
else
  log "Running environment doctor"
  ( cd "$BACKEND_DIR" && "$PY" -m app.deployment.doctor --fast ) || true
fi

cat <<EOF

${_C_BOLD}Setup complete.${_C_RESET}

Next steps:
  ./scripts/storeye start          # start backend + frontend in the background
  ./scripts/storeye seed           # load the demo store (idempotent)
  ./scripts/storeye status         # show URLs and health
  ./scripts/storeye stop           # stop everything

Docs: docs/quickstart_demo.md (showcase)  •  docs/quickstart_edge.md (edge deploy)
EOF
