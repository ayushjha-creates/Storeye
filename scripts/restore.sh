#!/usr/bin/env bash
# ============================================================================
# Storeye — restore a pg_dump backup (pg_restore).
#
# DESTRUCTIVE: the target database is dropped/recreated. Requires --yes.
#
# Usage:
#   ./scripts/restore.sh backups/storeye-<timestamp>.dump --yes
#   ./scripts/restore.sh backups/storeye-<timestamp>.dump --yes --test-db
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

load_env
pg_tools_available || die "PostgreSQL tools not found. Run ./scripts/setup.sh first."
pg_running || die "PostgreSQL is not running."

FILE=""
TARGET_DB=""
CONFIRMED=0

while [ $# -gt 0 ]; do
  case "$1" in
    --yes) CONFIRMED=1 ;;
    --test-db) TARGET_DB="$TEST_DB_NAME" ;;
    -h|--help) echo "Usage: scripts/restore.sh <backup.dump> [--yes] [--test-db]"; exit 0 ;;
    -*) die "Unknown option: $1" ;;
    *) FILE="$1" ;;
  esac
  shift
done

[ -n "$FILE" ] || die "Usage: scripts/restore.sh <backup.dump> --yes"
[ -f "$FILE" ] || die "Backup file not found: $FILE"
[ "$CONFIRMED" = "1" ] || die "This DESTROYS the target database. Re-run with --yes to confirm."

PY="$(venv_python)"
ensure_database_url
DB_FROM_URL="$("$PY" - "$DATABASE_URL" <<'PY'
import sys, urllib.parse
print(urllib.parse.urlsplit(sys.argv[1]).path.lstrip("/").split("/")[0])
PY
)"
: "${TARGET_DB:=$DB_FROM_URL}"

ensure_database "$TARGET_DB"

warn "Restoring '$FILE' into database '$TARGET_DB' (DESTRUCTIVE)"
log "Dropping and recreating $TARGET_DB"
"$PG_BIN/dropdb" -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" "$TARGET_DB"
"$PG_BIN/createdb" -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" "$TARGET_DB"

"$PG_BIN/pg_restore" -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" \
  --no-owner --no-privileges -d "$TARGET_DB" "$FILE" \
  || die "pg_restore reported errors (see output above)."

ok "Restore complete: $TARGET_DB"
if [ "$TARGET_DB" = "$DB_FROM_URL" ]; then
  warn "If this database stores the migrated schema, run './scripts/migrate.sh' to resync Alembic."
fi