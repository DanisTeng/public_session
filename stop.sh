#! /bin/bash
# stop.sh - 停止 public_session 主循环
# 用法: stop.sh [config_path]
# 写入 stop 文件，主循环检测到后会自动退出并清理 stop 文件
DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG="${1:-$DIR/config.json}"

# 从 config 中读取 stop_file 路径
STOP_FILE=$(python3 -c "
import json, os
with open('$CONFIG') as f:
    c = json.load(f)
print(os.path.expanduser(c.get('stop_file', '')))
")

if [ -z "$STOP_FILE" ]; then
  echo "ERROR: stop_file not found in config"
  exit 1
fi

touch "$STOP_FILE"
echo "✅  Stop file created at: $STOP_FILE"
echo "⏳  Waiting for public_session process to exit..."
