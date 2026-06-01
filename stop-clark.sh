#!/usr/bin/env bash
# Stop clark server gracefully.
# Usage: ./stop-clark.sh

set -euo pipefail

cd "$(dirname "$0")"
APP_DIR="$(pwd)"
PID_FILE="${APP_DIR}/data/clark.pid"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    PID=$(cat "$PID_FILE")
    echo "Stopping clark (PID: $PID)…"
    kill "$PID" 2>/dev/null

    # Wait up to 5s for graceful shutdown
    for i in $(seq 1 5); do
        if ! kill -0 "$PID" 2>/dev/null; then
            break
        fi
        sleep 1
    done

    # Force kill if still hanging
    if kill -0 "$PID" 2>/dev/null; then
        echo "Force killing…"
        kill -9 "$PID" 2>/dev/null
    fi

    rm -f "$PID_FILE"
    echo "clark stopped"
else
    # Fallback: pkill by pattern
    if pkill -f "uvicorn app.main:app" 2>/dev/null; then
        echo "clark stopped (by process name)"
    else
        echo "clark is not running"
    fi
    rm -f "$PID_FILE"
fi
