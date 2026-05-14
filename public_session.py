#!/usr/bin/env python3
"""
public_session.py — 公共会话主循环

1 秒固定心跳，OneTick 为唯一执行接口。

用法：public_session.py <config.json>

约定：
  - 飞书 APP_ID/APP_SECRET 走环境变量，不写进文件
  - 此脚本本身不包含任何用户/会话/环境特化信息

退出机制：
  - 主循环每秒检查 stop 文件，存在时 cleanup 后退出
"""

import os
import sys
import time
from datetime import datetime, timezone, timedelta

from config import Config, load as load_config

# ── 常量 ────────────────────────────────────────────────────────────────

HEARTBEAT_SECONDS = 1
HKT = timezone(timedelta(hours=8))


# ── 日志 ────────────────────────────────────────────────────────────────

def log(log_path, msg):
    """追加日志到指定文件"""
    ts = datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if log_path:
        od = os.path.dirname(log_path)
        if od:
            os.makedirs(od, exist_ok=True)
        with open(log_path, "a") as f:
            f.write(line + "\n")


# ── OneTick ─────────────────────────────────────────────────────────────

def one_tick(config: Config):
    """单次 tick 执行

    当前为框架骨架，后续在此函数中加入 session 发现与对话逻辑。

    Args:
        config: 配置
    """
    log_path = config.log_file

    log(log_path, "✅  OneTick done")


# ── Cleanup ──────────────────────────────────────────────────────────────

def cleanup(config: Config):
    """进程退出收尾

    清理资源、关闭连接、移除 stop 文件。

    Args:
        config: 配置
    """
    log_path = config.log_file
    log(log_path, "🧹  Cleanup: shutting down")

    # ── 清理 stop 文件，下次 run 不会立刻停止 ──
    stop_file = os.path.expanduser(config.stop_file)
    if stop_file and os.path.exists(stop_file):
        os.remove(stop_file)
        log(log_path, f"🗑️  Removed stop file: {stop_file}")

    log(log_path, "✅  Cleanup done")


# ── 主循环 ──────────────────────────────────────────────────────────────

def run_loop(config: Config):
    """主循环入口

    1 秒固定心跳，检测 stop 文件时执行 cleanup 后退出。

    Args:
        config: 配置
    """
    log_path = config.log_file
    stop_file = os.path.expanduser(config.stop_file)

    log(log_path, "🚀  Public session started")

    while True:
        tick_start = time.time()

        # 退出检查
        if stop_file and os.path.exists(stop_file):
            log(log_path, "🛑  Stop file detected, exiting")
            break

        # 执行 OneTick
        one_tick(config)

        # 心跳等待（补足到 1 秒）
        elapsed = time.time() - tick_start
        sleep_sec = max(0, HEARTBEAT_SECONDS - elapsed)
        time.sleep(sleep_sec)

    cleanup(config)


# ── 入口 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <config.json>", file=sys.stderr)
        sys.exit(1)

    config = load_config(sys.argv[1])
    run_loop(config)
