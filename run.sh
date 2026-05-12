#!/bin/bash
# run.sh — 后台启动 public_session 轮询守护进程
#
# 约定：
#   - PID 存于 state_dir/public-session.pid（由 PollLoop 自动管理）
#   - 日志存于 state_dir/public-session-daemon.log
#   - 停止守护：touch state_dir/public-session.stop（由 stop.sh 实现）

set -euo pipefail

CONFIG="${1:-config.json}"
[ -f "$CONFIG" ] || { echo "❌  Config not found: $CONFIG"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_ABS="$(cd "$(dirname "$CONFIG")" && pwd)/$(basename "$CONFIG")"

# 从 config 读 state_dir
STATE_DIR=$(python3 -c "
import json
with open('$CONFIG_ABS') as f:
    c = json.load(f)
print(c.get('state_dir', ''))
")
STATE_DIR="${STATE_DIR/#\~/$HOME}"

# 检查是否已在运行
PID_FILE="$STATE_DIR/public-session.pid"
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "⚠️  Already running (PID $OLD_PID)"
        echo "   Stop first: $(dirname "$0")/stop.sh $CONFIG"
        exit 1
    fi
    echo "🧹  Stale PID file removed"
    rm -f "$PID_FILE"
fi

mkdir -p "$STATE_DIR"
LOG_FILE="$STATE_DIR/public-session-daemon.log"

# 后台运行 PollLoop（--listen）
nohup python3 "$SCRIPT_DIR/public_session.py" "$CONFIG_ABS" --listen \
    > "$LOG_FILE" 2>&1 &
PID=$!

echo "✅  Started (PID $PID)"
echo "   Log: tail -f $LOG_FILE"
