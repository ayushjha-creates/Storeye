#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/backend"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate
pip install -r requirements.txt -q
pip install -r requirements-dev.txt -q

echo "Starting EdgeRetail-IQ backend..."
exec uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
