#!/bin/bash
# stop.sh — 停止 public_session 后台守护进程

set -euo pipefail

CONFIG="${1:-config.json}"
[ -f "$CONFIG" ] || { echo "❌  Config not found: $CONFIG"; exit 1; }

CONFIG_ABS="$(cd "$(dirname "$CONFIG")" && pwd)/$(basename "$CONFIG")"

STATE_DIR=$(python3 -c "
import json
with open('$CONFIG_ABS') as f:
    c = json.load(f)
print(c.get('state_dir', ''))
")
STATE_DIR="${STATE_DIR/#\~/$HOME}"

PID_FILE="$STATE_DIR/public-session.pid"
if [ ! -f "$PID_FILE" ]; then
    echo "📭  Not running"
    exit 0
fi

PID=$(cat "$PID_FILE")
if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    echo "✅  Stopped (PID $PID)"
else
    echo "📭  Process gone"
fi

rm -f "$PID_FILE"
