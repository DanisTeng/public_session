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

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

from config import Config, CachedTokenProvider, load as load_config
from message_manager import MessageManager, Message
from util.feishu import react_message

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


# ── Last Processed ─────────────────────────────────────────────────────

_LAST_PROCESSED_PATH: str | None = None


def _ensure_last_processed_path(config: Config) -> str:
    global _LAST_PROCESSED_PATH
    if _LAST_PROCESSED_PATH is not None:
        return _LAST_PROCESSED_PATH
    d = config.state_dir or os.path.dirname(config.log_file or ".")
    os.makedirs(d, exist_ok=True)
    _LAST_PROCESSED_PATH = os.path.join(d, "last_processed.json")
    return _LAST_PROCESSED_PATH


def _load_last_processed(config: Config) -> dict[str, str]:
    """{sender_id: last_msg_id}，空 dict 表示无记录"""
    path = _ensure_last_processed_path(config)
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return {}
        return {k: str(v) for k, v in raw.items()}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_last_processed(config: Config, lp: dict[str, str]):
    path = _ensure_last_processed_path(config)
    with open(path, "w") as f:
        json.dump(lp, f, indent=2)


def _process_new_messages(
    config: Config,
    mgr: MessageManager,
    token_provider: CachedTokenProvider,
):
    """OneTick 核心逻辑：处理所有未标记的 WS 消息。

    用 msg_id 判定处理边界：找到 last_processed 中的 last_msg_id，
    它之前（离列表头更近，即更新的消息）全部打 Done。
    最后持久化 last_processed 表。
    """
    log_path = config.log_file
    table = mgr.snapshot()
    if not table:
        return  # 空表，无事可做

    lp = _load_last_processed(config)
    total_processed = 0

    for sender_id, msgs in table.items():
        # msgs: [(message_id, text, create_time, sender_name), ...], newest first
        last_msg_id = lp.get(sender_id, "")

        if not last_msg_id:
            # 尚无记录，全部标记
            target_msgs = msgs
        else:
            # 找到 last_msg_id 的位置
            try:
                idx = next(i for i, (mid, _, _, _) in enumerate(msgs)
                           if mid == last_msg_id)
            except StopIteration:
                # last_msg_id 不在 snapshot 中（可能重启前处理的），全部标记
                target_msgs = msgs
            else:
                # 从 idx 往列表头方向（更新消息）是需要处理的
                target_msgs = msgs[:idx]

        for msg_id, text, _create_time, sender_name in target_msgs:
            token = token_provider.get()
            if not token:
                log(log_path, f"⚠️  Skipping {msg_id[:18]} from {sender_name}: no token")
                continue
            result = react_message(msg_id, token, emoji="Done")
            if result.get("code") == 0:
                total_processed += 1
            else:
                log(log_path,
                    f"⚠️  Done react failed for {sender_name} {msg_id[:18]}: "
                    f"{result.get('msg', 'unknown')}")

        # 更新此 sender 的最后处理消息（= 最新消息的 message_id）
        if msgs:
            lp[sender_id] = msgs[0][0]

    if total_processed:
        log(log_path, f"✅  Processed {total_processed} message(s)")

    _save_last_processed(config, lp)


# ── OneTick ─────────────────────────────────────────────────────────────

def one_tick(config: Config, mgr: MessageManager, token_provider: CachedTokenProvider):
    """单次 tick 执行

    Args:
        config: 配置
        mgr: MessageManager 实例
        token_provider: 缓存 token 提供者
    """
    _process_new_messages(config, mgr, token_provider)


# ── Cleanup ──────────────────────────────────────────────────────────────

def cleanup(config: Config, mgr: MessageManager):
    """进程退出收尾

    清理资源、关闭连接、移除 stop 文件。

    Args:
        config: 配置
        mgr: MessageManager 实例
    """
    log_path = config.log_file
    log(log_path, "🧹  Cleanup: shutting down")

    mgr.stop()

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

    # 启动 MessageManager（WS 后台线程）
    mgr = MessageManager(
        app_id=config.resolved_app_id,
        app_secret=config.resolved_app_secret,
        mark_get_on_receive=True,  # 立即打 Get 表示在线
    )
    mgr.start()

    token_provider = config.new_token_provider()

    log(log_path, "🚀  Public session started")

    while True:
        tick_start = time.time()

        # 退出检查
        if stop_file and os.path.exists(stop_file):
            log(log_path, "🛑  Stop file detected, exiting")
            break

        # 执行 OneTick
        one_tick(config, mgr, token_provider)

        # 心跳等待（补足到 1 秒）
        elapsed = time.time() - tick_start
        sleep_sec = max(0, HEARTBEAT_SECONDS - elapsed)
        time.sleep(sleep_sec)

    cleanup(config, mgr)


# ── 入口 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <config.json>", file=sys.stderr)
        sys.exit(1)

    config = load_config(sys.argv[1])
    run_loop(config)
