#!/usr/bin/env bash
# ============================================================================
# Storeye — shared shell helpers (sourced by the other scripts).
#
# macOS/Linux only. Targets Bash 3.2+ (macOS default) — avoid Bash 4 features.
# ============================================================================

# Resolve repo paths from this file's location (scripts/lib/common.sh).
_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$_LIB_DIR/../.." && pwd)"

BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
MODELS_DIR="$PROJECT_ROOT/models"
VENV_DIR="$BACKEND_DIR/.venv"

LOGS_DIR="$PROJECT_ROOT/logs"
LOGS_BACKEND="$LOGS_DIR/backend"
LOGS_AI="$LOGS_DIR/ai"
LOGS_FRONTEND="$LOGS_DIR/frontend"
RUN_DIR="$LOGS_DIR/run"
BACKUP_DIR="${STOREYE_BACKUP_DIR:-$PROJECT_ROOT/backups}"

# -- Output helpers ----------------------------------------------------------
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  _C_RESET="\033[0m"; _C_GREEN="\033[32m"; _C_YELLOW="\033[33m"
  _C_RED="\033[31m"; _C_BLUE="\033[34m"; _C_BOLD="\033[1m"
else
  _C_RESET=""; _C_GREEN=""; _C_YELLOW=""; _C_RED=""; _C_BLUE=""; _C_BOLD=""
fi

log()  { printf "${_C_BLUE}==>${_C_RESET} %s\n" "$*"; }
ok()   { printf "${_C_GREEN} ok ${_C_RESET} %s\n" "$*"; }
warn() { printf "${_C_YELLOW}warn${_C_RESET} %s\n" "$*" >&2; }
err()  { printf "${_C_RED}fail${_C_RESET} %s\n" "$*" >&2; }
die()  { err "$*"; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }

# -- Configuration defaults (overridable via env or backend/.env) ------------
: "${STOREYE_HOST:=0.0.0.0}"
: "${STOREYE_PORT:=8000}"
: "${STOREYE_FRONTEND_HOST:=0.0.0.0}"
: "${STOREYE_FRONTEND_PORT:=5173}"
: "${PGHOST:=localhost}"
: "${PGPORT:=5433}"
: "${PGUSER:=storeye}"
: "${PGDATA:=$PROJECT_ROOT/.pgdata}"
: "${DB_NAME:=storeye}"
: "${TEST_DB_NAME:=storeye_test}"

export PGHOST PGPORT PGUSER

# Load backend/.env (if present) so scripts see DATABASE_URL, ports, keys.
load_env() {
  local env_file="$BACKEND_DIR/.env" line key value
  [ -f "$env_file" ] || return 0
  while IFS= read -r line; do
    line="${line%%$'\r'}"
    case "$line" in
      '' | '#'*) continue ;;
    esac
    key="${line%%=*}"
    value="${line#*=}"
    [ "$key" = "$line" ] && continue
    # strip a trailing inline comment (a '#' preceded by whitespace)
    value="$(printf '%s' "$value" | sed -E 's/[[:space:]]+#.*$//')"
    # strip matching surrounding quotes so the value is exported verbatim
    case "$value" in
      \"*\") value=${value#\"}; value=${value%\"} ;;
      \'*\') value=${value#\'}; value=${value%\'} ;;
    esac
    export "$key=$value"
  done < "$env_file"
}

ensure_dirs() {
  mkdir -p "$LOGS_BACKEND" "$LOGS_AI" "$LOGS_FRONTEND" "$RUN_DIR"
}

# -- Venv / Python -----------------------------------------------------------
venv_python() { echo "$VENV_DIR/bin/python"; }

python_bin() {
  if [ -x "$VENV_DIR/bin/python" ]; then
    echo "$VENV_DIR/bin/python"
  elif have python3; then
    echo python3
  else
    echo ""
  fi
}

ensure_venv() {
  if [ ! -x "$VENV_DIR/bin/python" ]; then
    log "Creating Python virtualenv at backend/.venv"
    have python3 || die "python3 is required (install Python 3.9+)."
    python3 -m venv "$VENV_DIR" || die "Failed to create virtualenv."
  fi
}

# -- Database URL ------------------------------------------------------------
derive_db_url() {
  echo "postgresql+psycopg2://${PGUSER}@${PGHOST}:${PGPORT}/${DB_NAME}"
}

derive_test_db_url() {
  echo "postgresql+psycopg2://${PGUSER}@${PGHOST}:${PGPORT}/${TEST_DB_NAME}"
}

# Export DATABASE_URL for the app when the env file did not set one.
ensure_database_url() {
  if [ -z "${DATABASE_URL:-}" ]; then
    export DATABASE_URL="$(derive_db_url)"
    warn "DATABASE_URL was unset; using local default ($DATABASE_URL)"
  fi
}

# -- PostgreSQL --------------------------------------------------------------
find_pg_bin() {
  if [ -n "${STOREYE_PG_BIN:-}" ] && [ -x "${STOREYE_PG_BIN}/pg_ctl" ]; then
    echo "$STOREYE_PG_BIN"; return 0
  fi
  local d
  for d in /Library/PostgreSQL/*/bin /opt/homebrew/opt/postgresql@*/bin \
           /opt/homebrew/bin /usr/local/bin /usr/lib/postgresql/*/bin; do
    if [ -x "$d/pg_ctl" ]; then echo "$d"; return 0; fi
  done
  if have pg_ctl; then dirname "$(command -v pg_ctl)"; return 0; fi
  echo ""; return 1
}

PG_BIN="$(find_pg_bin || true)"
export PG_BIN

pg_tools_available() { [ -n "$PG_BIN" ] && [ -x "$PG_BIN/pg_ctl" ]; }

pg_running() {
  pg_tools_available || return 1
  "$PG_BIN/pg_ctl" -D "$PGDATA" status >/dev/null 2>&1
}

pg_port_busy() {
  if have lsof; then
    lsof -nP -iTCP:"$PGPORT" -sTCP:LISTEN >/dev/null 2>&1
  else
    (exec 3<>"/dev/tcp/127.0.0.1/$PGPORT") >/dev/null 2>&1
  fi
}

# -- Port / orphan-process helpers -------------------------------------------
# Return the PID listening on a TCP port (empty if none).
port_pid() {
  local port="$1"
  if have lsof; then
    lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -1 || true
  else
    echo ""
  fi
}

# Echo the command line of a PID (empty when gone).
process_command() {
  local pid="$1"
  [ -n "$pid" ] || return 0
  if have ps; then
    ps -o command= -p "$pid" 2>/dev/null || true
  fi
}

# Return 0 when a PID's command line contains the given pattern.
process_matches() {
  local pid="$1" pattern="$2"
  local cmd; cmd="$(process_command "$pid")"
  [ -n "$cmd" ] && printf '%s' "$cmd" | grep -q "$pattern"
}

# Kill any untracked listener on a port that matches one of our known command
# patterns (uvicorn backend / vite frontend). Returns 0 always.
clean_port_orphans() {
  local port="$1" pattern="$2"
  local pid; pid="$(port_pid "$port")"
  [ -n "$pid" ] || return 0
  if process_matches "$pid" "$pattern"; then
    warn "Cleaning orphaned process (pid $pid) on port $port"
    kill "$pid" >/dev/null 2>&1 || true
    sleep 1
  fi
}

ensure_postgres() {
  if pg_running; then
    ok "PostgreSQL already running (pgdata=$PGDATA, port=$PGPORT)"
    return 0
  fi
  pg_tools_available || die "PostgreSQL tools not found. Install PostgreSQL (e.g. 'brew install postgresql@18' or your OS package manager) and set STOREYE_PG_BIN if needed."
  if pg_port_busy; then
    die "Port $PGPORT is already in use but the project cluster is not running. Stop the other service or set PGPORT."
  fi
  if [ ! -s "$PGDATA/PG_VERSION" ]; then
    log "Initialising project-local PostgreSQL cluster at $PGDATA"
    mkdir -p "$PGDATA"
    "$PG_BIN/initdb" -D "$PGDATA" -U "$PGUSER" -A trust --encoding=UTF8 >/dev/null \
      || die "initdb failed."
  fi
  ensure_dirs
  log "Starting PostgreSQL (port $PGPORT)"
  "$PG_BIN/pg_ctl" -D "$PGDATA" -l "$LOGS_BACKEND/postgres.log" \
    -o "-p $PGPORT" -w start >/dev/null \
    || die "Failed to start PostgreSQL (see $LOGS_BACKEND/postgres.log)."
  ok "PostgreSQL started"
}

stop_postgres() {
  if pg_running; then
    log "Stopping PostgreSQL"
    "$PG_BIN/pg_ctl" -D "$PGDATA" -m fast -w stop >/dev/null 2>&1 || true
    ok "PostgreSQL stopped"
  fi
}

ensure_database() {
  local name="$1"
  local exists
  exists="$("$PG_BIN/psql" -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d postgres \
    -tAc "SELECT 1 FROM pg_database WHERE datname='$name'" 2>/dev/null || true)"
  if [ "$exists" = "1" ]; then
    ok "Database '$name' exists"
  else
    log "Creating database '$name'"
    "$PG_BIN/createdb" -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" "$name" \
      || die "Could not create database '$name'."
    ok "Database '$name' created"
  fi
}

# -- Process management (pid files) ------------------------------------------
pid_file() { echo "$RUN_DIR/$1.pid"; }

pid_alive() {
  local pf; pf="$(pid_file "$1")"
  [ -f "$pf" ] || return 1
  local pid; pid="$(cat "$pf" 2>/dev/null || true)"
  [ -n "$pid" ] || return 1
  kill -0 "$pid" >/dev/null 2>&1
}

read_pid() { cat "$(pid_file "$1")" 2>/dev/null || true; }

is_our_process() {
  local pid="$1" pattern="$2"
  [ -n "$pid" ] || return 1
  if have ps; then
    ps -o command= -p "$pid" 2>/dev/null | grep -q "$pattern"
  else
    return 0
  fi
}

# stop_pidfile NAME PATTERN — SIGTERM then SIGKILL, only if it's our process.
stop_pidfile() {
  local name="$1" pattern="$2" pid
  if ! pid_alive "$name"; then
    rm -f "$(pid_file "$name")"
    return 0
  fi
  pid="$(read_pid "$name")"
  if ! is_our_process "$pid" "$pattern"; then
    warn "PID $pid for $name does not look like ours; removing stale pidfile only."
    rm -f "$(pid_file "$name")"
    return 0
  fi
  log "Stopping $name (pid $pid)"
  kill "$pid" >/dev/null 2>&1 || true
  local i=0
  while kill -0 "$pid" >/dev/null 2>&1 && [ "$i" -lt 20 ]; do
    sleep 0.5; i=$((i + 1))
  done
  if kill -0 "$pid" >/dev/null 2>&1; then
    warn "$name did not stop gracefully; sending SIGKILL"
    kill -9 "$pid" >/dev/null 2>&1 || true
  fi
  rm -f "$(pid_file "$name")"
  ok "$name stopped"
}

# -- HTTP helpers ------------------------------------------------------------
wait_for_http() {
  local url="$1" timeout="${2:-60}" i=0
  while [ "$i" -lt "$timeout" ]; do
    if http_ok "$url"; then return 0; fi
    sleep 1; i=$((i + 1))
  done
  return 1
}

http_ok() {
  if have curl; then
    curl -fsS --max-time 3 "$1" >/dev/null 2>&1
  else
    "$(python_bin)" - "$1" <<'PY' >/dev/null 2>&1
import sys, urllib.request
urllib.request.urlopen(sys.argv[1], timeout=3).read(1)
PY
  fi
}

# -- Misc --------------------------------------------------------------------
BACKEND_URL() { echo "http://localhost:${STOREYE_PORT}"; }
FRONTEND_URL() { echo "http://localhost:${STOREYE_FRONTEND_PORT}"; }

require_cmd() {
  have "$1" || die "Required command '$1' not found in PATH."
}
