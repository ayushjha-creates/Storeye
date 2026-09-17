#!/usr/bin/env bash
# ============================================================================
# Storeye — run the backend in the foreground (dev).
#
# Prefers the background service manager:
#     ./scripts/storeye start          (daemon + pid file + logs)
#
# This script sources common helpers (fixes the historical scripts/backend
# directory bug), loads backend/.env, creates the venv on first run, and runs
# uvicorn in the foreground for interactive development.
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

load_env
ensure_venv

[ -x "$VENV_DIR/bin/pip" ] || die "pip missing (run ./scripts/setup.sh)"
if ! "$(venv_python)" -c "import fastapi" >/dev/null 2>&1; then
  log "Installing backend Python dependencies"
  "$VENV_DIR/bin/pip" install -r "$BACKEND_DIR/requirements.txt" -q
fi

if [ "$#" -eq 0 ]; then
  ensure_database_url
fi

log "Starting Storeye backend at ${STOREYE_HOST}:${STOREYE_PORT}"
( cd "$BACKEND_DIR" && DATABASE_URL="${DATABASE_URL:-}" exec "$(venv_python)" -m uvicorn \
    app.main:app --reload --host "$STOREYE_HOST" --port "$STOREYE_PORT" )