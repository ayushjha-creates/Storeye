#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/../backend"

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi

source .venv/bin/activate
pip install -r requirements.txt -q
pip install -r requirements-dev.txt -q

# Storeye business/data tests MUST run against the isolated PostgreSQL test DB.
# TEST_DATABASE_URL must point at PostgreSQL (never a temporary SQLite DB) and
# must NOT be the production `storeye` database. The conftest guard enforces both.
export TEST_DATABASE_URL="${TEST_DATABASE_URL:-postgresql+psycopg2://storeye@localhost:5433/storeye_test}"
export DATABASE_URL="${TEST_DATABASE_URL}"  # for the alembic steps below

echo "Verifying Alembic head..."
alembic heads

echo "Applying full Alembic migration chain on the test database (idempotent)..."
alembic upgrade head

echo "Checking models vs migrations (Alembic drift check)..."
alembic check

echo "Running tests (PostgreSQL = ${TEST_DATABASE_URL})..."
exec pytest tests/ -v