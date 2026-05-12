#!/usr/bin/env python3
"""
public_session.py — 公共会话通道监听装置

通过飞书 bot 周期性拉取会话消息，处理来自特定用户的新消息，
收到后自动标记 Get 已读。

用法：public_session.py <config.json>

约定：
  - config 文件声明 bot 身份、目标用户、会话等信息
  - 飞书 APP_ID/APP_SECRET 走环境变量（避免写进文件）
  - 此脚本本身不包含任何用户/会话/环境特化信息

状态文件（存于 state_dir 下）：
  processed_messages.json — 已处理消息 ID 列表，保证幂等
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

from util import config as cfg
from util import feishu

# ── 日志 ────────────────────────────────────────────────────────────────

HKT = timezone(timedelta(hours=8))


def log(log_path, msg):
    """追加日志到指定文件"""
    ts = datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if log_path:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a") as f:
            f.write(line + "\n")


# ── 消息处理 ────────────────────────────────────────────────────────────


def is_user_message(msg, target_open_id):
    """判断消息是否来自目标用户

    支持的消息类型：text, image, file
    """
    sender = msg.get("sender", {})
    sender_type = sender.get("sender_type", "")
    sender_id = sender.get("id", "")
    msg_type = msg.get("msg_type", "")
    if sender_type != "user":
        return False
    if target_open_id and sender_id != target_open_id:
        return False
    if msg_type not in ("text", "image", "file"):
        return False
    return True


def extract_preview(msg):
    """提取消息的简短文本概览"""
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


def process_messages(c):
    """拉取新消息 → 过滤 → 标记已读"""
    log_path = c.get("log_file", "")
    state_dir = os.path.expanduser(c["state_dir"])

    log(log_path, "▶️  Starting public_session check")

    # 从环境变量获取 bot 身份
    app_id = os.environ.get(c["env_app_id"])
    app_secret = os.environ.get(c["env_app_secret"])
    if not app_id or not app_secret:
        log(log_path, f"❌  Env vars {c['env_app_id']}/{c['env_app_secret']} not set")
        return

    token = feishu.get_token(app_id, app_secret)
    if not token:
        log(log_path, "❌  Get token failed")
        return

    chat_id = c.get("chat_id", "")
    target_open_id = c.get("target_user_open_id", "")

    result = feishu.list_messages(chat_id, token, page_size=20)
    if result.get("code") != 0:
        log(log_path, f"❌  List messages failed: {result.get('msg', '')}")
        return

    items = result.get("data", {}).get("items", [])
    if not items:
        log(log_path, "📭  No messages in chat")
        return

    # 加载已处理消息状态
    state_file = os.path.join(state_dir, "processed_messages.json")
    if os.path.exists(state_file):
        with open(state_file) as f:
            state = json.load(f)
    else:
        state = {"processed_message_ids": []}

    new_count = 0

    for msg in items:
        msg_id = msg.get("message_id", "")
        if msg_id in state["processed_message_ids"]:
            continue
        if not is_user_message(msg, target_open_id):
            continue

        preview = extract_preview(msg)
        log(log_path, f"📩  New message: [{msg_id[:20]}...] {preview}")

        # 标记已读
        react_result = feishu.react_message(msg_id, token, emoji="Get")
        if react_result.get("code") == 0:
            log(log_path, f"✅  Get reaction added to {msg_id[:20]}...")
        else:
            code = react_result.get("code")
            if code == 1000001:  # 已加过表情
                log(log_path, f"ℹ️  Already reacted to {msg_id[:20]}...")
            else:
                log(log_path, f"⚠️  React failed: {react_result.get('msg', '')}")

        state["processed_message_ids"].append(msg_id)
        new_count += 1

    # 清理旧记录
    if len(state["processed_message_ids"]) > 200:
        state["processed_message_ids"] = state["processed_message_ids"][-200:]

    state["last_process_time"] = datetime.now(HKT).isoformat()

    # 原子写入
    os.makedirs(state_dir, exist_ok=True)
    tmp = state_file + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, state_file)

    if new_count > 0:
        log(log_path, f"✅  Processed {new_count} new message(s)")
    else:
        log(log_path, f"📭  No new messages (processed {len(items)} total)")


# ── 入口 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <config.json>", file=sys.stderr)
        sys.exit(1)

    config = cfg.load(sys.argv[1])
    process_messages(config)
