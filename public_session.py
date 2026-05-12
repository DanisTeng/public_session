#!/usr/bin/env python3
"""
public_session.py — 公共会话通道消息处理

提供 OneTick() 供外部（cron 或 PollLoop）调用。

单次执行（cron）：
  python3 public_session.py config.json

持续轮询（监听）：
  python3 public_session.py config.json --listen

约定：
  - 配置信息存 config.json
  - flybook APP_ID/APP_SECRET 走环境变量
  - 状态文件存 state_dir 目录
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

from util import config as cfg
from util import feishu
from util import polling

# ── 常量 ────────────────────────────────────────────────────────────────

HKT = timezone(timedelta(hours=8))

BOT_SENDER_TYPE = "app"
"""飞书 bot 自身 sender_type，用于过滤 bot 自己发出的消息。"""

USER_MSG_TYPES = ("text", "image", "file")
"""OneTick 关心的用户消息类型。"""


# ── 日志 ────────────────────────────────────────────────────────────────


def log(log_path, msg):
    """追加日志到指定文件。log_path 为空时只打 stdout。

    Args:
        log_path: 日志文件路径或空字符串
        msg: 日志消息
    """
    ts = datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if log_path:
        dirname = os.path.dirname(log_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with open(log_path, "a") as f:
            f.write(line + "\n")


# ── 状态文件 ────────────────────────────────────────────────────────────


def load_state(state_dir):
    """加载 processed_messages.json 状态文件。

    Args:
        state_dir: 状态文件所在目录

    Returns:
        dict
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
    """原子写入状态文件。先写 tmp 再 rename。

    Args:
        state_dir: 状态文件所在目录
        state: 待写入的 dict
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


def is_user_message(msg, target_open_id=""):
    """判断消息是否来自目标用户。

    只关心用户（sender_type=user）发来的 text/image/file 消息。
    Bot 自身消息（sender_type=app）直接跳过。

    Pre-condition:
        msg 来自 list_messages 返回的 items

    Args:
        msg: 飞书消息 dict
        target_open_id: 期望的 open_id（空 = 不过滤）

    Returns:
        bool
    """
    sender = msg.get("sender", {})
    sender_type = sender.get("sender_type", "")

    if sender_type == BOT_SENDER_TYPE:
        return False
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
    """提取消息简短文本概览，用于日志。

    Args:
        msg: 飞书消息 dict

    Returns:
        str: 最长 80 字符
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


# ── OneTick ─────────────────────────────────────────────────────────────


def OneTick(config):
    """单次执行的消息处理循环。

    流程：拉消息 → 过滤已处理 → 用户消息打 Get → 更新状态。
    每次保证完整执行，不会中途退出。

    Args:
        config: 配置 dict，需要字段见 config.json

    Returns:
        dict: {
            "has_new_user_msg": bool,
            "new_msg_count": int,
            "processed_count": int,
            "error": str | None,
        }
    """
    log_path = config.get("log_file", "")
    state_dir = os.path.expanduser(config["state_dir"])
    log(log_path, "▶️  OneTick start")

    # 获取 token
    app_id = os.environ.get(config["env_app_id"])
    app_secret = os.environ.get(config["env_app_secret"])
    if not app_id or not app_secret:
        log(log_path, f"❌  Env vars {config['env_app_id']}/{config['env_app_secret']} not set")
        return {"has_new_user_msg": False, "new_msg_count": 0, "error": "env_missing"}

    token = feishu.get_token(app_id, app_secret)
    if not token:
        log(log_path, "❌  Get token failed")
        return {"has_new_user_msg": False, "new_msg_count": 0, "error": "token_failed"}

    # 拉取消息
    chat_id = config.get("chat_id", "")
    target_open_id = config.get("target_user_open_id", "")
    page_size = config.get("page_size", 50)

    result = feishu.list_messages(chat_id, token, page_size=page_size)
    if result.get("code") != 0:
        log(log_path, f"❌  List messages failed: {result.get('msg', '')}")
        return {"has_new_user_msg": False, "new_msg_count": 0, "error": "list_failed"}

    items = result.get("data", {}).get("items", [])

    # 处理消息
    state = load_state(state_dir)
    processed_ids = set(state["processed_message_ids"])

    new_count = 0
    has_new_user_msg = False

    for msg in items:
        msg_id = msg.get("message_id", "")

        if msg_id in processed_ids:
            continue

        if is_user_message(msg, target_open_id):
            preview = extract_preview(msg)
            sender_id = msg.get("sender", {}).get("id", "")
            log(log_path, f"📩  New msg: {msg_id[:20]}... from={sender_id[-12:]} {preview}")

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
            log(log_path, f"📭  Skip (non-user): {msg_id[:20]}... type={msg.get('msg_type','?')}")

        state["processed_message_ids"].append(msg_id)

    # 裁剪
    MAX_RECORDS = 500
    if len(state["processed_message_ids"]) > MAX_RECORDS:
        state["processed_message_ids"] = state["processed_message_ids"][-MAX_RECORDS:]

    state["last_tick_time"] = datetime.now(HKT).isoformat()
    save_state(state_dir, state)

    log(log_path, f"🏁  OneTick done: {new_count} new / {len(items)} total")

    return {
        "has_new_user_msg": has_new_user_msg,
        "new_msg_count": new_count,
        "processed_count": len(items),
        "error": None,
    }


# ── 入口 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <config.json> [--listen]", file=sys.stderr)
        sys.exit(1)

    config = cfg.load(sys.argv[1])

    if "--listen" in sys.argv:
        loop = polling.PollLoop(
            config=config,
            tick_fn=OneTick,
            tick_interval=config.get("tick_interval_seconds", 300),
        )
        loop.run()
    else:
        OneTick(config)
