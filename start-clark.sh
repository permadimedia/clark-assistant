#!/usr/bin/env bash
# Start clark server as a background process.
# Usage: ./start-clark.sh

set -euo pipefail

cd "$(dirname "$0")"
APP_DIR="$(pwd)"
PID_FILE="${APP_DIR}/data/clark.pid"
LOG_FILE="${APP_DIR}/data/clark.log"
HOST="127.0.0.1"
PORT="8124"

# Check if already running
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "clark is already running (PID: $(cat "$PID_FILE"))"
    exit 0
fi

# Ensure data/ and .venv exist
mkdir -p "${APP_DIR}/data"

if [ ! -d "${APP_DIR}/.venv" ]; then
    echo "Error: .venv not found. Run: uv sync"
    exit 1
fi

# Start uvicorn in background
nohup "${APP_DIR}/.venv/bin/python" -m uvicorn app.main:app \
    --host "$HOST" --port "$PORT" \
    --workers 1 --no-access-log \
    > "$LOG_FILE" 2>&1 &

PID=$!
echo $PID > "$PID_FILE"

# Wait briefly and verify
sleep 2
if kill -0 "$PID" 2>/dev/null; then
    echo "clark started (PID: $PID) — http://${HOST}:${PORT}"
else
    echo "clark failed to start — check ${LOG_FILE}"
    tail -5 "$LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
fi
