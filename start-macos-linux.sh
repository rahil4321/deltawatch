#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
if [[ ! -d "$ROOT/backend/.venv" ]]; then
  python3 -m venv "$ROOT/backend/.venv"
fi
source "$ROOT/backend/.venv/bin/activate"
python -m pip install --upgrade pip
pip install -r "$ROOT/backend/requirements.txt"
python -m playwright install chromium
if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  (cd "$ROOT/frontend" && npm install)
fi
(cd "$ROOT/backend" && uvicorn app.main:app --reload --port 8000) &
BACKEND_PID=$!
trap 'kill "$BACKEND_PID" 2>/dev/null || true' EXIT
cd "$ROOT/frontend"
npm run dev
