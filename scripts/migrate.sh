#!/usr/bin/env bash
# ============================================================================
# Storeye — apply database migrations (Alembic upgrade head).
#
# Non-destructive. Run after setting DATABASE_URL (backend/.env is loaded
# automatically). Verifies the schema is at head with `alembic check`.
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

load_env
ensure_database_url
ensure_dirs

[ -x "$VENV_DIR/bin/alembic" ] || die "Alembic not installed. Run ./scripts/setup.sh first."

log "Migrating $DATABASE_URL"
( cd "$BACKEND_DIR" && "$VENV_DIR/bin/alembic" upgrade head ) || die "alembic upgrade head failed."

if ( cd "$BACKEND_DIR" && "$VENV_DIR/bin/alembic" check >/dev/null 2>&1 ); then
  ok "Schema is at head (alembic check clean)"
else
  warn "alembic check reported differences; inspect with:"
  warn "  (cd backend && ./.venv/bin/alembic check)"
fi
