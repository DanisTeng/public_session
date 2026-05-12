#!/bin/bash
# run.sh - 运行 public_session 监听装置
# 用法: run.sh [config_path]
# 默认 config: 同目录下的 config.yaml

DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG="${1:-$DIR/config.json}"
cd "$DIR"
python3 public_session.py "$CONFIG"
