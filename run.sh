#!/bin/bash
# run.sh — 启动 public session 后台守护进程
#
# 用法：./run.sh <config.json>
#   在后台启动 public_session.py --listen
#   PID 写入 state_dir/public-session.pid
#
# 停止：./stop.sh <config.json>

set -euo pipefail

CONFIG="${1:-config.json}"
if [ ! -f "$CONFIG" ]; then
    echo "❌  Config not found: $CONFIG"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_ABS="$(cd "$(dirname "$CONFIG")" && pwd)/$(basename "$CONFIG")"

# 从 config 里读 state_dir（Python 一行搞定）
STATE_DIR=$(python3 -c "
import json
with open('$CONFIG_ABS') as f:
    c = json.load(f)
print(c.get('state_dir', ''))
")

# 展开 ~
STATE_DIR="${STATE_DIR/#\~/$HOME}"

# 检查是否已经在运行
PID_FILE="$STATE_DIR/public-session.pid"
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "⚠️  Public session already running (PID $OLD_PID)"
        echo "   Stop it first: $(dirname "$0")/stop.sh $CONFIG"
        exit 1
    else
        echo "🧹  Stale PID file removed"
        rm -f "$PID_FILE"
    fi
fi

mkdir -p "$STATE_DIR"

# 后台启动 listen_loop
LOG_FILE="$STATE_DIR/public-session-daemon.log"
nohup python3 "$SCRIPT_DIR/public_session.py" "$CONFIG_ABS" --listen \
    > "$LOG_FILE" 2>&1 &
PID=$!
echo "$PID" > "$PID_FILE"

echo "✅  Public session started (PID $PID)"
echo "   Log:  tail -f $LOG_FILE"
echo "   Stop: $(dirname "$0")/stop.sh $CONFIG"
