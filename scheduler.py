"""scheduler.py - 对话调度器

根据 MessageManager snapshot 和 last_processed 状态，找出"最久等待"的 sender。
"""

import time
from dataclasses import dataclass
from typing import Optional

from message_manager import MessageManager


# ── 数据结构 ────────────────────────────────────────────────────────────

@dataclass
class Candidate:
    """最久等待候选者

    Attributes:
        sender_id: 发送者 open_id
        sender_name: 发送者名字
        wait_seconds: 最早一条未处理消息已等待的秒数
        first_msg_id: 最早一条未处理消息的 message_id
    """
    sender_id: str
    sender_name: str
    wait_seconds: float
    first_msg_id: str


# ── 调度器 ──────────────────────────────────────────────────────────────

def pick_candidate(
    mgr: MessageManager,
    last_processed: dict[str, str],
) -> Optional[Candidate]:
    """从所有 sender 中选出最久等待的候选。

    算法：
      1. 遍历 snapshot 中所有 sender
      2. 对每个 sender，用 last_processed 确定未处理消息的范围
      3. 选择未处理消息中最早一条等待最久的 sender

    Args:
        mgr: MessageManager 实例
        last_processed: {sender_id: last_msg_id}，来自 _load_last_processed

    Returns:
        Candidate 或 None（无未处理消息）
    """
    table = mgr.snapshot()
    if not table:
        return None

    now = time.time()
    best: Optional[Candidate] = None

    for sender_id, msgs in table.items():
        if not msgs:
            continue

        # msgs 是 newest-first: [Message, ...]
        last_msg_id = last_processed.get(sender_id, "")

        if not last_msg_id:
            earliest_msg = msgs[-1]
        else:
            try:
                idx = next(i for i, msg in enumerate(msgs)
                           if msg.message_id == last_msg_id)
            except StopIteration:
                earliest_msg = msgs[-1]
            else:
                if idx == 0:
                    continue  # 没有新消息
                earliest_msg = msgs[idx - 1]

        try:
            earliest_create_time = float(earliest_msg.create_time)
        except (ValueError, TypeError):
            continue

        wait_seconds = now - (earliest_create_time / 1000.0)
        if wait_seconds < 0:
            wait_seconds = 0

        if best is None or wait_seconds > best.wait_seconds:
            best = Candidate(
                sender_id=sender_id,
                sender_name=earliest_msg.sender_name,
                wait_seconds=wait_seconds,
                first_msg_id=earliest_msg.message_id,
            )

    return best
