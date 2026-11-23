#!/usr/bin/env bash
# Start Wenflow at http://localhost:8000  (builds the web app first if it is missing or out of date)
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"

if [ ! -f web/dist/index.html ] || [ -n "$(find web/src web/index.html -newer web/dist/index.html -print -quit 2>/dev/null)" ]; then
  echo "Building the web app…"
  (cd web && { [ -d node_modules ] || npm install --no-fund --no-audit; } && npm run build)
fi

cd server
if [ ! -x .venv/bin/uvicorn ]; then
  echo "Installing Python dependencies…"
  uv sync
fi
echo "Wenflow is starting on http://localhost:${PORT:-8000}"
exec .venv/bin/uvicorn wenflow.main:app --host 127.0.0.1 --port "${PORT:-8000}"
