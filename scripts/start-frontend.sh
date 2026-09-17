#!/usr/bin/env bash
# ============================================================================
# Storeye — run the frontend in the foreground (dev).
#
# Prefers the background service manager:
#     ./scripts/storeye start          (daemon + pid file + logs)
#
# This script sources common helpers, installs frontend deps on first run, and
# runs `npm run dev` in the foreground for interactive development.
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

have node || die "node/npm not found. Install Node.js 20+ or use a prebuilt frontend."

if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  log "Installing frontend dependencies"
  ( cd "$FRONTEND_DIR" && npm install --no-audit --no-fund )
fi

log "Starting Storeye frontend at ${STOREYE_FRONTEND_HOST}:${STOREYE_FRONTEND_PORT}"
( cd "$FRONTEND_DIR" && exec npm run dev -- \
    --host "$STOREYE_FRONTEND_HOST" --port "$STOREYE_FRONTEND_PORT" )