#!/usr/bin/env python3
"""
public_session.py — 公共会话通道主循环

常驻 Python 进程，0.5s 高精度轮询。
OneTick 为唯一执行接口，自适应间隔调度 + 标志位立即触发。

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

# ── 常量 ────────────────────────────────────────────────────────────────

TICK_INTERVAL_SECONDS = 300      # 5 分钟
MAIN_LOOP_SLEEP_SECONDS = 0.5    # 主循环轮询间隔
HKT = timezone(timedelta(hours=8))


# ── 日志 ────────────────────────────────────────────────────────────────

def log(log_path, msg):
    """追加日志到指定文件"""
    ts = datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if log_path:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a") as f:
            f.write(line + "\n")


# ── 状态读写 ────────────────────────────────────────────────────────────

def _load_state(state_dir):
    """加载 processed_messages.json

    Returns:
        dict: 当前状态，文件不存在时返回默认空状态
    """
    state_file = os.path.join(state_dir, "processed_messages.json")
    if os.path.exists(state_file):
        with open(state_file) as f:
            return json.load(f)
    return {"processed_message_ids": []}


def _save_state(state_dir, state):
    """原子写入状态文件"""
    state_file = os.path.join(state_dir, "processed_messages.json")
    state["last_tick_time"] = datetime.now(HKT).isoformat()
    os.makedirs(state_dir, exist_ok=True)
    tmp = state_file + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, state_file)


# ── 调度 ────────────────────────────────────────────────────────────────

def _next_tick_after(elapsed):
    """自适应间隔调度，公式 1

    固定 5 分钟间隔，执行长了少等，执行短了多等。

    Args:
        elapsed: 本次 OneTick 执行耗时（秒）

    Returns:
        float: 下一次 OneTick 的绝对时间戳
    """
    wait = max(0.0, TICK_INTERVAL_SECONDS - elapsed)
    return time.time() + wait


# ── OneTick ─────────────────────────────────────────────────────────────

def one_tick(c):
    """单次 tick 执行，原子不可中断

    空闲态和占用态的逻辑都在此函数内判断。
    当前为空骨架，业务逻辑后续填充。

    Args:
        c: 配置 dict

    Returns:
        float: 本次 tick 执行耗时（秒）
    """
    log_path = c.get("log_file", "")
    start = time.time()

    # ── 加载当前状态
    state_dir = os.path.expanduser(c["state_dir"])
    state = _load_state(state_dir)

    # ── TODO: 双态状态机业务逻辑 ──
    # 1. 根据 state["state"] 分支：
    #    空闲态：拉消息 → Get 已读 → 判断是否进入占用态
    #    占用态：与当前用户对话 → 退出判定

    log(log_path, "🕐  OneTick running (skeleton)")

    # ── 持久化状态
    _save_state(state_dir, state)

    elapsed = time.time() - start
    log(log_path, f"✅  OneTick done ({elapsed:.1f}s)")
    return elapsed


# ── Cleanup ──────────────────────────────────────────────────────────────

def cleanup(c):
    """整体退出收尾，只执行一次

    清理资源、关闭连接。

    Args:
        c: 配置 dict
    """
    log_path = c.get("log_file", "")
    log(log_path, "🧹  Cleanup: shutting down public session")

    # ── TODO: 清理逻辑 ──
    # - 关闭 WS 长连接（若有）
    # - 清理临时文件

    log(log_path, "✅  Cleanup done")


# ── SessionController（外界回调接口）─────────────────────────────────────

class SessionController:
    """主循环的外界控制器

    用于 WS 回调线程或其他并发上下文向主循环发送信号。
    需与主循环共享 trigger_flag 和 next_tick_time。
    """

    def __init__(self):
        self.trigger_flag = False
        self.next_tick_time = float('inf')

    def invalidate(self):
        """设置立即触发标志

        外界事件（如 WS 推送）调用此方法，主循环在下一轮
        0.5s 轮询中立即响应。
        """
        self.trigger_flag = True
        self.next_tick_time = float('inf')


# ── 主循环 ──────────────────────────────────────────────────────────────

def run_loop(c, controller=None):
    """主循环入口

    0.5s 轮询，检查触发条件（定时 / 标志位）和执行 OneTick。
    发现 stop 文件时执行 cleanup 后退出。

    Args:
        c: 配置 dict
        controller: SessionController 实例（可选），用于外界发信号
    """
    log_path = c.get("log_file", "")
    stop_file = os.path.expanduser(c.get("stop_file", ""))

    # ── 如果没传 controller，创建一个局部的 ──
    if controller is None:
        controller = SessionController()

    # ── 初始化调度：首次 OneTick 立即触发 ──
    next_tick_time = time.time()
    controller.next_tick_time = next_tick_time

    log(log_path, "🚀  Public session started")

    # ── 主循环 ──
    while True:
        # 退出检查
        if stop_file and os.path.exists(stop_file):
            log(log_path, "🛑  Stop file detected, exiting")
            break

        # 触发判断
        if controller.trigger_flag or time.time() >= controller.next_tick_time:
            controller.trigger_flag = False
            controller.next_tick_time = float('inf')

            # 执行 OneTick
            elapsed = one_tick(c)

            # 调度下一次
            controller.next_tick_time = _next_tick_after(elapsed)

        time.sleep(MAIN_LOOP_SLEEP_SECONDS)

    # ── Cleanup（进程退出时一次性执行）──
    cleanup(c)


# ── 入口 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <config.json>", file=sys.stderr)
        sys.exit(1)

    config = cfg.load(sys.argv[1])
    run_loop(config)
