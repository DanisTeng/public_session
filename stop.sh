#!/bin/bash
# stop.sh — 优雅停止 public_session 守护进程
#
# 做法：在 state_dir 下创建 stop 标志文件，PollLoop 会在
# 一轮完整的 OneTick 结束后检测到并自行退出，然后清理资源。

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

STOP_FILE="$STATE_DIR/public-session.stop"
PID_FILE="$STATE_DIR/public-session.pid"

if [ ! -f "$PID_FILE" ] && [ ! -f "$STOP_FILE" ]; then
    echo "📭  Not running"
    exit 0
fi

# 写 stop 标志（PollLoop 检测到后会在一轮 tick 结束后清理退出）
touch "$STOP_FILE"
echo "⏹️  Stop signal sent (touch $STOP_FILE)"

# 等进程退出（最多等 tick_interval + 额外时间）
PID=""
[ -f "$PID_FILE" ] && PID=$(cat "$PID_FILE")

if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    echo "⏳  Waiting for process $PID to exit gracefully..."
    WAIT_MAX=360
    WAITED=0
    while kill -0 "$PID" 2>/dev/null && [ $WAITED -lt $WAIT_MAX ]; do
        sleep 1
        WAITED=$((WAITED + 1))
    done
    if kill -0 "$PID" 2>/dev/null; then
        echo "⚠️  Timeout, force killing..."
        kill -9 "$PID" 2>/dev/null || true
    fi
    echo "✅  Process exited"
fi

# 清理残留文件
rm -f "$STOP_FILE" "$PID_FILE"
echo "✅  Stopped"
