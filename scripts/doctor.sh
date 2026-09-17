#!/usr/bin/env bash
# ============================================================================
# Storeye — environment doctor (read-only readiness check).
#
# Usage:
#   ./scripts/doctor.sh                # full check (DB + deep model imports)
#   ./scripts/doctor.sh --fast         # skip deep model import checks
#   ./scripts/doctor.sh --no-db        # skip PostgreSQL checks
#   ./scripts/doctor.sh --json
#   ./scripts/doctor.sh --api-url http://localhost:8000 --frontend-url http://localhost:5173
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

load_env
ensure_venv

( cd "$BACKEND_DIR" && DATABASE_URL="${DATABASE_URL:-}" "$(venv_python)" -m app.deployment.doctor "$@" )
