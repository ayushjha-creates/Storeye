#!/usr/bin/env bash
# ============================================================================
# Storeye — show component status (PostgreSQL, backend, frontend).
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

load_env

printf "\n${_C_BOLD}Storeye status${_C_RESET}\n"

# -- PostgreSQL --------------------------------------------------------------
if pg_tools_available && pg_running; then
  ok "PostgreSQL   running (pgdata=$PGDATA, port=$PGPORT)"
elif pg_port_busy; then
  warn "PostgreSQL   another server is listening on port $PGPORT (not the project cluster)"
else
  err "PostgreSQL   not running (start with ./scripts/start.sh)"
fi

# -- Backend -----------------------------------------------------------------
if pid_alive backend; then
  if http_ok "$(BACKEND_URL)/api/health"; then
    ok "Backend      healthy at $(BACKEND_URL) (pid $(read_pid backend))"
  else
    warn "Backend      process $(read_pid backend) alive but /api/health unreachable"
  fi
else
  err "Backend      not running"
fi

# -- Frontend ----------------------------------------------------------------
if pid_alive frontend; then
  if http_ok "$(FRONTEND_URL)"; then
    ok "Frontend     ready at $(FRONTEND_URL) (pid $(read_pid frontend))"
  else
    warn "Frontend     process $(read_pid frontend) alive but not responding"
  fi
else
  warn "Frontend     not running"
fi

# -- Database schema ---------------------------------------------------------
if [ -n "${DATABASE_URL:-}" ] && have curl; then
  rev="$(curl -fsS --max-time 3 "$(BACKEND_URL)/api/system/status" 2>/dev/null || true)"
  if [ -n "$rev" ]; then
    printf "\n${_C_BLUE}system${_C_RESET}       %s\n" "$rev"
  fi
fi
echo
