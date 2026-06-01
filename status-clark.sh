#!/usr/bin/env bash
# Check clark server status.
# Usage: ./status-clark.sh

set -euo pipefail

cd "$(dirname "$0")"
APP_DIR="$(pwd)"
PID_FILE="${APP_DIR}/data/clark.pid"
HOST="127.0.0.1"
PORT="8124"

echo "┌────────────────────────────────────────────────┐"
echo "│  clark — Ask clark.                            │"
echo "└────────────────────────────────────────────────┘"

# ── PID check ────────────────────────────────────────────
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    PID=$(cat "$PID_FILE")
    RUNTIME=$(ps -o etime= -p "$PID" 2>/dev/null | xargs)
    echo "  Process:   running  (PID: $PID, up: ${RUNTIME:-?})"
else
    echo "  Process:   not running"
    echo ""
    echo "  Start:  ./start-clark.sh"
    echo "  Stop:   ./stop-clark.sh"
    exit 1
fi

# ── Port check ───────────────────────────────────────────
if ss -tln 2>/dev/null | grep -q ":${PORT} "; then
    echo "  Port:      ${HOST}:${PORT}  (listening)"
else
    echo "  Port:      ${HOST}:${PORT}  (not listening — restart?)"
    exit 1
fi

# ── HTTP health ──────────────────────────────────────────
HEALTH=$(curl -sf "http://${HOST}:${PORT}/api/health" 2>/dev/null || echo "")
if [ -n "$HEALTH" ]; then
    VERSION=$(echo "$HEALTH" | python3 -c "import sys,json; print(json.load(sys.stdin).get('version','?'))" 2>/dev/null)
    echo "  API:       healthy  (v${VERSION})"
else
    echo "  API:       unreachable"
    exit 1
fi

# ── Modules ──────────────────────────────────────────────
MODULES=$(curl -sf "http://${HOST}:${PORT}/api/modules" 2>/dev/null \
    | python3 -c "import sys,json; ms=json.load(sys.stdin); print(', '.join(m['name'] for m in ms if m['config'].get('enabled')))" 2>/dev/null)
if [ -n "$MODULES" ]; then
    echo "  Modules:   $MODULES"
fi

echo "└────────────────────────────────────────────────┘"
