#!/usr/bin/env bash
# ============================================================================
# Storeye — start PostgreSQL + backend + frontend in the background.
#
# Idempotent: already-running components are left alone. PIDs are written to
# logs/run/*.pid and logs go to logs/{backend,frontend}/*.log.
#
# Usage:
#   ./scripts/start.sh                 # everything
#   ./scripts/start.sh --backend-only
#   ./scripts/start.sh --frontend-only
#   ./scripts/start.sh --no-db         # do not touch PostgreSQL
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

BACKEND_ONLY=0
FRONTEND_ONLY=0
START_DB=1
for arg in "$@"; do
  case "$arg" in
    --backend-only) BACKEND_ONLY=1 ;;
    --frontend-only) FRONTEND_ONLY=1 ;;
    --no-db) START_DB=0 ;;
    -h|--help) echo "Usage: scripts/start.sh [--backend-only|--frontend-only] [--no-db]"; exit 0 ;;
    *) die "Unknown option: $arg" ;;
  esac
done

load_env
ensure_dirs
ensure_venv
PY="$(venv_python)"

# -- PostgreSQL --------------------------------------------------------------
if [ "$START_DB" = "1" ] && [ "$FRONTEND_ONLY" = "0" ]; then
  ensure_postgres || warn "PostgreSQL not started; backend may be degraded."
fi

# -- Backend -----------------------------------------------------------------
if [ "$FRONTEND_ONLY" = "0" ]; then
  if pid_alive backend; then
    ok "Backend already running (pid $(read_pid backend))"
  else
    [ -x "$VENV_DIR/bin/uvicorn" ] || die "uvicorn not found. Run ./scripts/setup.sh first."
    ensure_database_url
    # A stale `storeye start`/CTRL-C can leave an untracked uvicorn behind.
    clean_port_orphans "$STOREYE_PORT" "uvicorn"
    log "Starting backend on ${STOREYE_HOST}:${STOREYE_PORT}"
    spawn_detached "$(pid_file backend)" "$BACKEND_DIR" "$LOGS_BACKEND/storeye-backend.log" \
      "$VENV_DIR/bin/uvicorn" app.main:app --host "$STOREYE_HOST" --port "$STOREYE_PORT"
    NEW_PID="$(read_pid backend)"
    if wait_for_http "$(BACKEND_URL)/api/health" 60; then
      LISTENER="$(port_pid "$STOREYE_PORT")"
      if [ -n "$LISTENER" ] && [ "$LISTENER" != "$NEW_PID" ]; then
        warn "Port ${STOREYE_PORT} is served by an untracked process ($LISTENER);"
        warn "our instance (pid $NEW_PID) may have exited — see $LOGS_BACKEND/storeye-backend.log"
      else
        ok "Backend healthy at $(BACKEND_URL) (pid $NEW_PID)"
      fi
    else
      warn "Backend did not become healthy in time — see $LOGS_BACKEND/storeye-backend.log"
    fi
  fi
fi

# -- Frontend ----------------------------------------------------------------
if [ "$BACKEND_ONLY" = "0" ]; then
  VITE_BIN="$FRONTEND_DIR/node_modules/.bin/vite"
  if pid_alive frontend; then
    ok "Frontend already running (pid $(read_pid frontend))"
  elif [ ! -x "$VITE_BIN" ]; then
    warn "Vite not installed ($VITE_BIN). Run ./scripts/setup.sh (needs Node)."
  else
    clean_port_orphans "$STOREYE_FRONTEND_PORT" "vite"
    log "Starting frontend on ${STOREYE_FRONTEND_HOST}:${STOREYE_FRONTEND_PORT}"
    CI=true spawn_detached "$(pid_file frontend)" "$FRONTEND_DIR" "$LOGS_FRONTEND/storeye-frontend.log" \
      "$VITE_BIN" --host "$STOREYE_FRONTEND_HOST" --port "$STOREYE_FRONTEND_PORT" --strictPort
    if wait_for_http "$(FRONTEND_URL)" 60; then
      ok "Frontend ready at $(FRONTEND_URL) (pid $(read_pid frontend))"
    else
      warn "Frontend did not respond in time — see $LOGS_FRONTEND/storeye-frontend.log"
    fi
  fi
fi

echo
bash "$SCRIPT_DIR/status.sh" || true
