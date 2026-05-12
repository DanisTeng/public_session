#!/usr/bin/env python3
"""
public_session.py — 公共会话通道主循环

单次执行模式：通过 cron 每 5 分钟触发一次 OneTick()。
OneTick 完成：
  1. 拉取指定会话的新消息
  2. 过滤飞书 bot 自身发出的消息（不处理）
  3. 给用户发来的新消息打 Get 表情（已读标记）
  4. 更新 processed_messages.json 状态文件

用法（单次执行，适合 cron）：
  python3 public_session.py <config.json>

用法（持续监听）：
  python3 public_session.py <config.json> --listen

约定：
  - config 文件声明 bot 身份、目标用户、会话、PM agent 等信息
  - 飞书 APP_ID/APP_SECRET 走环境变量（避免写进文件）
  - 此脚本本身不包含任何用户/会话/环境特化信息
"""

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

from util import config as cfg
from util import feishu

# ── 常量 ────────────────────────────────────────────────────────────────

HKT = timezone(timedelta(hours=8))

BOT_SENDER_TYPE = "app"
"""飞书 bot 自己的 sender_type，用于过滤出 bot 自己发的消息"""

USER_MSG_TYPES = ("text", "image", "file")
"""我们关心的用户消息类型"""

# ── 日志 ────────────────────────────────────────────────────────────────


def log(log_path, msg):
    """追加日志到指定文件

    Args:
        log_path: 日志文件路径（None 或空字符串 = 只打 stdout）
        msg: 日志消息
    """
    ts = datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if log_path:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a") as f:
            f.write(line + "\n")


# ── 状态文件 ────────────────────────────────────────────────────────────


def load_state(state_dir):
    """加载 processed_messages.json 状态文件

    Args:
        state_dir: 状态文件目录

    Returns:
        dict: {
            "processed_message_ids": [str],  已处理消息 ID 列表
            "last_tick_time": str | None,    上次 OneTick 时间（ISO格式）
        }
    """
    state_file = os.path.join(state_dir, "processed_messages.json")
    if os.path.exists(state_file):
        with open(state_file) as f:
            return json.load(f)
    return {
        "processed_message_ids": [],
        "last_tick_time": None,
    }


def save_state(state_dir, state):
    """原子写入 processed_messages.json 状态文件

    Args:
        state_dir: 状态文件目录
        state: 要写入的 state dict
    """
    state_file = os.path.join(state_dir, "processed_messages.json")
    os.makedirs(state_dir, exist_ok=True)
    tmp = state_file + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, state_file)


# ── 消息过滤 ────────────────────────────────────────────────────────────


def is_user_message(msg, target_open_id):
    """判断消息是否来自目标用户

    只关心用户发来的 text/image/file 消息。
    飞书 bot 自身发出的消息（sender_type=app）直接跳过。

    Args:
        msg: 飞书消息对象（list_messages 返回的 items 中一项）
        target_open_id: 目标用户 open_id。如果为空则不过滤用户。

    Returns:
        bool: 是目标用户发来的有效消息
    """
    sender = msg.get("sender", {})
    sender_type = sender.get("sender_type", "")

    # 跳过 bot 自身发出的消息
    if sender_type == BOT_SENDER_TYPE:
        return False
    # 只处理用户消息
    if sender_type != "user":
        return False

    sender_id = sender.get("id", "")
    if target_open_id and sender_id != target_open_id:
        return False

    msg_type = msg.get("msg_type", "")
    if msg_type not in USER_MSG_TYPES:
        return False

    return True


def extract_preview(msg):
    """提取消息的简短文本概览（用于日志）

    Args:
        msg: 飞书消息对象

    Returns:
        str: 文本预览（最多 80 字符）
    """
    msg_type = msg.get("msg_type", "unknown")
    content_raw = msg.get("body", {}).get("content", "{}")
    try:
        content = json.loads(content_raw)
    except json.JSONDecodeError:
        content = {}

    if msg_type == "text":
        return content.get("text", "")[:80]
    elif msg_type == "image":
        return "[image]"
    elif msg_type == "file":
        return f"[file: {content.get('file_name', '')}]"
    return f"[{msg_type}]"


# ── OneTick 主函数 ─────────────────────────────────────────────────────


def OneTick(config):
    """单次执行主循环

    拉取消息 → 过滤 → 标记 Get 已读 → 更新状态文件。
    每次执行只处理增量消息（通过 processed_message_ids 去重）。

    适合 cron 调度：执行完就退出，不阻塞。

    返回值可用于外部判断是否触发后续操作：
      dict: {
          "has_new_user_msg": bool,   是否有新的用户消息
          "new_msg_count": int,       新用户消息数量
          "processed_count": int,     本次拉取到的消息总数
      }

    Args:
        config: 配置 dict（通过 cfg.load 加载）

    Returns:
        dict: OneTick 执行摘要
    """
    log_path = config.get("log_file", "")
    state_dir = os.path.expanduser(config["state_dir"])

    log(log_path, "▶️  OneTick start")

    # ── 获取 token ──
    app_id = os.environ.get(config["env_app_id"])
    app_secret = os.environ.get(config["env_app_secret"])
    if not app_id or not app_secret:
        log(log_path, f"❌  Env vars {config['env_app_id']}/{config['env_app_secret']} not set")
        return {"has_new_user_msg": False, "new_msg_count": 0, "error": "env_missing"}

    token = feishu.get_token(app_id, app_secret)
    if not token:
        log(log_path, "❌  Get token failed")
        return {"has_new_user_msg": False, "new_msg_count": 0, "error": "token_failed"}

    # ── 拉取消息 ──
    chat_id = config.get("chat_id", "")
    target_open_id = config.get("target_user_open_id", "")
    page_size = config.get("page_size", 50)

    result = feishu.list_messages(chat_id, token, page_size=page_size)
    if result.get("code") != 0:
        log(log_path, f"❌  List messages failed: {result.get('msg', '')}")
        return {"has_new_user_msg": False, "new_msg_count": 0, "error": "list_failed"}

    items = result.get("data", {}).get("items", [])

    # ── 加载状态 ──
    state = load_state(state_dir)

    new_count = 0
    has_new_user_msg = False

    for msg in items:
        msg_id = msg.get("message_id", "")

        # 跳过已处理的
        if msg_id in state["processed_message_ids"]:
            continue

        # 判断是否是我们关心的用户消息
        if is_user_message(msg, target_open_id):
            preview = extract_preview(msg)
            sender = msg.get("sender", {}).get("id", "")
            log(log_path, f"📩  New msg: {msg_id[:20]}... from={sender[-12:]} {preview}")

            # 标记 Get 已读
            react_result = feishu.react_message(msg_id, token, emoji="Get")
            react_code = react_result.get("code")
            if react_code == 0:
                log(log_path, f"✅  Get → {msg_id[:20]}...")
            elif react_code == 1000001:
                log(log_path, f"ℹ️  Already got → {msg_id[:20]}...")
            else:
                log(log_path, f"⚠️  React failed: {react_result.get('msg', '')}")

            has_new_user_msg = True
            new_count += 1
        else:
            # 非用户消息（bot 自发的等），仅记录已处理，不打 Get
            log(log_path, f"📭  Skip (non-user): {msg_id[:20]}... type={msg.get('msg_type','?')}")

        # 无论是否用户消息，都标记为已处理（避免重复处理 bot 自己的消息）
        state["processed_message_ids"].append(msg_id)

    # ── 清理旧记录（最多保留 500 条） ──
    MAX_RECORDS = 500
    if len(state["processed_message_ids"]) > MAX_RECORDS:
        state["processed_message_ids"] = state["processed_message_ids"][-MAX_RECORDS:]

    state["last_tick_time"] = datetime.now(HKT).isoformat()

    # ── 保存状态 ──
    save_state(state_dir, state)

    log(log_path, f"🏁  OneTick done: {new_count} new / {len(items)} total")

    return {
        "has_new_user_msg": has_new_user_msg,
        "new_msg_count": new_count,
        "processed_count": len(items),
        "error": None,
    }


# ── 持续监听模式 ────────────────────────────────────────────────────────


def listen_loop(config):
    """持续运行模式：每 N 秒轮询一次 OneTick

    用于开发调试：无需配 cron，跑着就行。

    生产环境建议直接用 cron 触发单次执行，更稳定。

    Args:
        config: 配置 dict
    """
    tick_interval = config.get("tick_interval_seconds", 60)
    log_path = config.get("log_file", "")

    log(log_path, f"🔄  Listen loop started (interval={tick_interval}s)")
    log(log_path, "    Press Ctrl+C to stop")

    try:
        while True:
            OneTick(config)
            time.sleep(tick_interval)
    except KeyboardInterrupt:
        log(log_path, "🛑  Listen loop stopped by user")


# ── 入口 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <config.json> [--listen]", file=sys.stderr)
        sys.exit(1)

    config = cfg.load(sys.argv[1])

    if "--listen" in sys.argv:
        listen_loop(config)
    else:
        OneTick(config)
