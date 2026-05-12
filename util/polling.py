"""
polling.py — 轮询循环封装

对外暴露 PollLoop 类，管理 stop 信号、定时轮询和资源清理。

通信方式（约定）：
  - stop_file: 存在此文件表示"请优雅停止"。PollLoop 会在一轮完整
    OneTick 结束后退出，然后调用 clean_up 清理 stop_file 和 pid_file。
  - pid_file: 记录守护进程 PID，用于检测是否已在运行。

用法示例：
    from util import polling

    def tick(config):
        # 执行一次业务逻辑
        return {"done": True}

    loop = polling.PollLoop(
        config=config,
        tick_fn=OneTick,
        tick_interval=300,
    )
    loop.run()
"""

import os
import sys
import time
from datetime import datetime, timezone, timedelta

HKT = timezone(timedelta(hours=8))

# ── 工具函数 ────────────────────────────────────────────────────────────


def log(path, msg):
    """追加日志到文件。path 为空时只打 stdout。

    Args:
        path: 日志文件路径或空字符串
        msg: 日志消息
    """
    ts = datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if path:
        dirname = os.path.dirname(path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with open(path, "a") as f:
            f.write(line + "\n")


# ── 状态目录路径辅助 ─────────────────────────────────────────────────────


def _resolve_state_dir(state_dir):
    """展开 ~ 为 HOME 目录

    Args:
        state_dir: 可能含有 ~ 的路径字符串

    Returns:
        str: 展开后的绝对路径
    """
    return os.path.expanduser(state_dir)


def _stop_file(state_dir):
    return os.path.join(_resolve_state_dir(state_dir), "public-session.stop")


def _pid_file(state_dir):
    return os.path.join(_resolve_state_dir(state_dir), "public-session.pid")


def _daemon_log(state_dir):
    return os.path.join(_resolve_state_dir(state_dir), "public-session-daemon.log")


# ── PollLoop ────────────────────────────────────────────────────────────


class PollLoop:
    """轮询循环控制器

    Attributes:
        config: 配置 dict（需至少包含 state_dir）
        tick_fn: 每次轮询调用的函数，接收 config 为参数
        tick_interval: 轮询间隔（秒）
        initialized: run() 是否已被调用过（禁止重复运行）
        _stopped: 内部停止标志位，True 后 stop_file 已被触发
    """

    def __init__(self, config, tick_fn, tick_interval=300):
        """初始化 PollLoop

        Args:
            config: 配置 dict，至少包含 state_dir
            tick_fn: 单次执行函数，签名 fn(config) → dict
            tick_interval: 轮询间隔（秒），默认 300
        """
        self.config = config
        self.tick_fn = tick_fn
        self.tick_interval = tick_interval
        self.initialized = False
        self._stopped = False

    def run(self):
        """启动轮询循环。

        流程：
          1. 检查 stop_file，如果已存在则先清除（上次异常遗留）
          2. 写入 PID 文件
          3. 进入主循环：每轮先检查 stop → 执行 tick → sleep → 检查 stop → sleep ...
          4. 检测到 stop 信号或发生异常时清理退出

        注意：
          - 本函数是阻塞的，直到检测到 stop 信号
          - tick_fn 的每次执行保证完整跑完再检查 stop
          - tick_fn 执行期间即使有人 touch stop 文件，也会等本轮 tick 结束后才退出
        """
        state_dir = self.config.get("state_dir", "")
        log_path = _daemon_log(state_dir)

        # 防止重复运行
        if self.initialized:
            log(log_path, "⚠️  PollLoop already initialized, skipping")
            return
        self.initialized = True

        # 清除可能残留的 stop 文件（上次异常遗留）
        sf = _stop_file(state_dir)
        if os.path.exists(sf):
            os.remove(sf)
            log(log_path, "🧹  Cleaned leftover stop file")

        # 写入 PID
        pf = _pid_file(state_dir)
        os.makedirs(os.path.dirname(pf), exist_ok=True)
        with open(pf, "w") as f:
            f.write(str(os.getpid()))

        log(log_path, f"🔄  Poll loop started (interval={self.tick_interval}s)")
        log(log_path, f"    Stop file: {sf}")

        try:
            while not self._check_stop(state_dir, log_path):
                # 先执行一次 tick（保证至少完整跑一次）
                self.tick_fn(self.config)

                # 等一个完整间隔，期间每秒检查 stop 信号
                slept = 0
                while slept < self.tick_interval:
                    if self._check_stop(state_dir, log_path):
                        break
                    time.sleep(1)
                    slept += 1
        except KeyboardInterrupt:
            log(log_path, "🛑  KeyboardInterrupt, cleaning up...")
        except Exception as e:
            log(log_path, f"🔥  Unhandled exception: {e}")
            raise
        finally:
            self.clean_up(state_dir, log_path)
            log(log_path, "✅  Poll loop stopped")

    def _check_stop(self, state_dir, log_path):
        """检查 stop 文件是否存在。

        考虑到外层循环会持续调用此函数，第一次检测到 stop 文件时
        记录日志并设置标志。此后循环依然返回 True，直到 clean_up
        删除 stop 文件。

        Returns:
            bool: True 表示应该退出
        """
        sf = _stop_file(state_dir)
        exists = os.path.exists(sf)
        if exists and not self._stopped:
            self._stopped = True
            log(log_path, "⏹️  Stop signal received, finishing current round...")
        return exists or self._stopped

    def clean_up(self, state_dir, log_path=""):
        """清理 stop 文件和 PID 文件。由 run() 的 finally 块自动调用。

        Args:
            state_dir: 状态目录
            log_path: 日志路径（可选）
        """
        sf = _stop_file(state_dir)
        if os.path.exists(sf):
            os.remove(sf)
            log(log_path, "🧹  stop file removed")

        pf = _pid_file(state_dir)
        if os.path.exists(pf):
            os.remove(pf)
            log(log_path, "🧹  pid file removed")
