#!/usr/bin/env bash
# ============================================================================
# Storeye — PostgreSQL backup (pg_dump, custom format).
#
# Backups are written to:  backups/  (git-ignored). Restore with
# ./scripts/restore.sh backups/storeye-<timestamp>.dump
#
# Usage:
#   ./scripts/backup.sh             # dump the business DB
#   ./scripts/backup.sh --test-db   # dump the test database instead
#   ./scripts/backup.sh --all       # dump both databases
#   ./scripts/backup.sh --out DIR   # destination directory
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

TARGET_DB=""
ALL=0
OUT="$BACKUP_DIR"

while [ $# -gt 0 ]; do
  case "$1" in
    --all) ALL=1 ;;
    --test-db) TARGET_DB="$TEST_DB_NAME" ;;
    --out) OUT="$2"; shift ;;
    -h|--help) echo "Usage: scripts/backup.sh [--all|--test-db] [--out DIR]"; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
  shift
done

load_env
pg_tools_available || die "PostgreSQL tools not found. Run ./scripts/setup.sh first."
pg_running || die "PostgreSQL is not running."

PY="$(venv_python)"
ensure_database_url
DB_FROM_URL="$("$PY" - "$DATABASE_URL" <<'PY'
import sys, urllib.parse
print(urllib.parse.urlsplit(sys.argv[1]).path.lstrip("/").split("/")[0])
PY
)"

mkdir -p "$OUT"
STAMP="$(date +%Y%m%d-%H%M%S)"

backup_one() {
  local db="$1"
  local file="$OUT/${db}-${STAMP}.dump"
  log "Backing up database '$db' -> $file"
  "$PG_BIN/pg_dump" -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" \
    --format=custom --no-owner --no-privileges -f "$file" "$db"
  ok "Backup written: $file ($(du -h "$file" | cut -f1))"
}

if [ "$ALL" = "1" ]; then
  backup_one "$DB_NAME"
  backup_one "$TEST_DB_NAME"
elif [ -n "$TARGET_DB" ]; then
  backup_one "$TARGET_DB"
else
  backup_one "$DB_FROM_URL"
fi