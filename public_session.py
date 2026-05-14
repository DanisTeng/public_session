#!/usr/bin/env python3
"""
public_session.py — 公共会话通道主循环

常驻 Python 进程，1 秒固定心跳。
OneTick 为唯一执行接口。

用法：public_session.py <config.json>

约定：
  - config 文件声明 bot 身份、目标用户、会话等信息
  - 飞书 APP_ID/APP_SECRET 走环境变量（避免写进文件）
  - 此脚本本身不包含任何用户/会话/环境特化信息

退出机制：
  - 主循环轮询检查 stop 文件（config 中指定路径）
  - 文件存在时执行 cleanup 后退出
"""

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

from util import config as cfg
from util.feishu import get_token

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

def one_tick(c):
    """单次 tick 执行

    当前为框架骨架：获取 token 后记录日志。
    后续在此函数中加入 session 发现与对话逻辑。

    Args:
        c: 配置 dict
    """
    log_path = c.get("log_file", "")

    # ── 获取 token（骨架验证） ──
    app_id = os.environ.get(c["env_app_id"])
    app_secret = os.environ.get(c["env_app_secret"])
    if not app_id or not app_secret:
        log(log_path, "❌  Missing APP_ID or APP_SECRET env vars")
        return

    token = get_token(app_id, app_secret)
    if not token:
        log(log_path, "❌  Failed to get tenant_access_token")
        return

    log(log_path, "✅  OneTick done")


# ── Cleanup ──────────────────────────────────────────────────────────────

def cleanup(c):
    """进程退出收尾

    清理资源、关闭连接、移除 stop 文件。

    Args:
        c: 配置 dict
    """
    log_path = c.get("log_file", "")
    log(log_path, "🧹  Cleanup: shutting down")

    # ── 清理 stop 文件，下次 run 不会立刻停止 ──
    stop_file = os.path.expanduser(c.get("stop_file", ""))
    if stop_file and os.path.exists(stop_file):
        os.remove(stop_file)
        log(log_path, f"🗑️  Removed stop file: {stop_file}")

    log(log_path, "✅  Cleanup done")


# ── 主循环 ──────────────────────────────────────────────────────────────

def run_loop(c):
    """主循环入口

    1 秒固定心跳，检测 stop 文件时执行 cleanup 后退出。

    Args:
        c: 配置 dict
    """
    log_path = c.get("log_file", "")
    stop_file = os.path.expanduser(c.get("stop_file", ""))

    log(log_path, "🚀  Public session started")

    while True:
        tick_start = time.time()

        # 退出检查
        if stop_file and os.path.exists(stop_file):
            log(log_path, "🛑  Stop file detected, exiting")
            break

        # 执行 OneTick
        one_tick(c)

        # 心跳等待（补足到 1 秒）
        elapsed = time.time() - tick_start
        sleep_sec = max(0, HEARTBEAT_SECONDS - elapsed)
        time.sleep(sleep_sec)

    cleanup(c)


# ── 入口 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <config.json>", file=sys.stderr)
        sys.exit(1)

    config = cfg.load(sys.argv[1])
    run_loop(config)
