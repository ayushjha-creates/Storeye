#!/usr/bin/env bash
# ============================================================================
# Storeye — deterministic demo reset.
#
# Deletes ONLY the demo store's data and re-seeds it from the M21 seed, so the
# demo always returns to the same baseline. Non-demo stores are never touched.
#
# Usage:
#   ./scripts/demo-reset.sh            # reset the demo store
#   ./scripts/demo-reset.sh --verify   # reset twice and prove determinism
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

VERIFY=0
for arg in "$@"; do
  case "$arg" in
    --verify) VERIFY=1 ;;
    -h|--help)
      echo "Usage: scripts/demo-reset.sh [--verify]"; exit 0 ;;
    *) die "Unknown option: $arg" ;;
  esac
done

load_env
ensure_database_url
ensure_venv
PY="$(venv_python)"

if [ "$VERIFY" = "1" ]; then
  log "Verifying deterministic demo reset (two reset+seed cycles)"
  ( cd "$BACKEND_DIR" && DATABASE_URL="$DATABASE_URL" \
      "$PY" -m scripts.demo_verify ) || die "Demo reset is NOT deterministic."
  ok "Deterministic reset verified"
  exit 0
fi

log "Resetting demo store ($DATABASE_URL)"
( cd "$BACKEND_DIR" && DATABASE_URL="$DATABASE_URL" \
    "$PY" -m scripts.seed_demo --reset ) || die "Demo reset failed."
ok "Demo store reset to baseline"
