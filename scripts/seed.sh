#!/usr/bin/env bash
# ============================================================================
# Storeye — seed the demo store (idempotent, deterministic).
#
# Reuses the M21 seed (backend/scripts/seed_demo.py). Running it twice without
# --reset updates the existing demo rows (fixed UUIDs); with --reset it deletes
# ONLY the demo store's rows first. Non-demo stores are never touched.
#
# Usage:
#   ./scripts/seed.sh            # idempotent seed
#   ./scripts/seed.sh --reset    # reset the demo store, then seed
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

load_env
ensure_database_url
ensure_venv

log "Seeding demo store ($DATABASE_URL)"
( cd "$BACKEND_DIR" && DATABASE_URL="$DATABASE_URL" \
    "$(venv_python)" -m scripts.seed_demo "$@" ) || die "Demo seed failed."
ok "Demo seed complete"
