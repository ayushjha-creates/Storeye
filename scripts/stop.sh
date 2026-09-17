#!/usr/bin/env bash
# ============================================================================
# Storeye — stop backend, frontend and (by default) the project PostgreSQL.
#
# Only processes whose recorded PID matches our known command pattern are
# signalled, so unrelated services are never killed. Graceful SIGTERM first,
# SIGKILL after a short grace period.
#
# Usage:
#   ./scripts/stop.sh             # app + project PostgreSQL
#   ./scripts/stop.sh --keep-db   # leave PostgreSQL running
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

KEEP_DB=0
CLEAN_ORPHANS=0
for arg in "$@"; do
  case "$arg" in
    --keep-db) KEEP_DB=1 ;;
    --clean-orphans) CLEAN_ORPHANS=1 ;;
    -h|--help) echo "Usage: scripts/stop.sh [--keep-db] [--clean-orphans]"; exit 0 ;;
    *) die "Unknown option: $arg" ;;
  esac
done

load_env

stop_pidfile frontend "vite"
stop_pidfile backend "uvicorn"

if [ "$CLEAN_ORPHANS" = "1" ]; then
  clean_port_orphans "$STOREYE_PORT" "uvicorn"
  clean_port_orphans "$STOREYE_FRONTEND_PORT" "vite"
fi

if [ "$KEEP_DB" = "1" ]; then
  warn "Leaving PostgreSQL running (--keep-db)"
else
  pg_tools_available && stop_postgres || true
fi

ok "Storeye stopped"
