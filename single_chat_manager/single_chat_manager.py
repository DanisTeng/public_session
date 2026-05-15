"""
single_chat_manager — 单次完整会话的执行器

SingleChatManager 负责一次完整的 single chat：从选定 sender、前情提要、
执行对话到退出，全部在 run() 中阻塞完成。

一次 run() = 一个完整的"接待-聊天-结束"周期。

MVP 版本（传声筒）：
  - 收到 sender 消息 → PM bot 回复"看到了"（占位，将来调 OpenClaw）
  - 回复成功后更新 last_processed + 打 Done 标记
  - 30 秒无回复超时结束
  - 每轮对话记入 messages.log
"""

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from config import CachedTokenProvider
from message_manager import MessageManager
from scheduler import Candidate

HKT = timezone(timedelta(hours=8))

# ── 常量 ────────────────────────────────────────────────────────────────

_IDLE_TIMEOUT = 30          # 30 秒无回复超时
_POLL_INTERVAL = 1          # 轮询间隔 1 秒
_LOG_FILE_EXT = "messages"  # 日志文件名后缀


# ── 数据结构 ────────────────────────────────────────────────────────────

@dataclass
class ChatResult:
    """一次 single chat 的执行结果"""
    sender_id: str
    sender_name: str
    message_count: int = 0      # 本次会话处理的消息数量
    timed_out: bool = False
    error: Optional[str] = None


@dataclass
class _SessionState:
    """运行时状态"""
    last_msg_id: str            # 已经处理到的消息 id
    last_activity: float        # 上次有消息的时间戳


# ── 日志 ────────────────────────────────────────────────────────────────

def _ts():
    return datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S")


def _log_line(msg: str, candidate: Candidate, log_file: str = ""):
    line = f"[{_ts()}] [chat {candidate.sender_name}] {msg}"
    print(line, flush=True)
    if log_file:
        od = os.path.dirname(log_file)
        if od:
            os.makedirs(od, exist_ok=True)
        with open(log_file, "a") as f:
            f.write(line + "\n")


# ── Last Processed 持久化 ──────────────────────────────────────────────

def _ensure_last_processed_path(config) -> str:
    d = config.state_dir or os.path.dirname(config.log_file or ".")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "last_processed.json")


def _load_last_processed(config) -> dict[str, str]:
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


def _save_last_processed(config, lp: dict[str, str]):
    path = _ensure_last_processed_path(config)
    with open(path, "w") as f:
        json.dump(lp, f, indent=2)


# ── SingleChatManager ──────────────────────────────────────────────────

class SingleChatManager:
    """一次完整 single chat 的执行器。

    MVP（传声筒版本）：
      - 从 snapshot 中读取指定 sender 的新消息
      - 对每条新消息：回复"看到了" → 标记 Done → 更新 last_processed
      - 所有 unprocessed 消息处理完后，等待新消息
      - 30 秒无新消息 → 超时结束

    run() 是唯一公共入口，阻塞执行，返回 ChatResult。
    """

    def __init__(
        self,
        config,
        mgr: MessageManager,
        token_provider: CachedTokenProvider,
        candidate: Candidate,
    ):
        self._config = config
        self._mgr = mgr
        self._token_provider = token_provider
        self._candidate = candidate
        self._log_file = config.log_file or ""

        self._result = ChatResult(
            sender_id=candidate.sender_id,
            sender_name=candidate.sender_name,
        )

    # ── 公共入口 ──

    def run(self) -> ChatResult:
        """执行一次完整的 single chat。

        阻塞执行，包含从前情提要、聊天到退出的完整周期。

        Returns:
            ChatResult: 本次会话的结果
        """
        c = self._candidate

        # 初始化状态：从 last_processed 拿到此 sender 的处理断点
        lp = _load_last_processed(self._config)
        last_msg_id = lp.get(c.sender_id, "")

        state = _SessionState(
            last_msg_id=last_msg_id,
            last_activity=time.time(),
        )

        _log_line(f"📞 开始会话 (last={last_msg_id[:18] or 'none'})", c, self._log_file)

        # 先处理已有的未处理消息
        self._process_existing(c, state)

        # 进入等待循环
        while True:
            now = time.time()

            # 检查是否有新消息
            new_msg = self._poll_new_message(c, state)
            if new_msg:
                state.last_activity = now
                self._process_one_message(c, new_msg[0], new_msg[1],
                                          new_msg[2], new_msg[3], state)
                continue

            # 超时检查
            idle = now - state.last_activity
            if idle >= _IDLE_TIMEOUT:
                _log_line(f"⏱️  超时（{_IDLE_TIMEOUT}s 无消息）", c, self._log_file)
                self._result.timed_out = True
                break

            time.sleep(_POLL_INTERVAL)

        _log_line(f"✅ 会话结束，共处理 {self._result.message_count} 条消息",
                  c, self._log_file)
        return self._result

    # ── 内部方法 ──

    def _process_existing(self, c: Candidate, state: _SessionState):
        """处理所有处于 unprocessed 状态的消息（即 last_processed 之后的）"""
        table = self._mgr.snapshot()
        msgs = table.get(c.sender_id, [])
        if not msgs:
            return

        # 找到断点
        if state.last_msg_id:
            try:
                idx = next(i for i, (mid, _, _, _) in enumerate(msgs)
                           if mid == state.last_msg_id)
            except StopIteration:
                idx = -1  # 断点不在 snapshot 中，全部处理
        else:
            idx = -1  # 无断点，全部处理

        if idx == 0:
            return  # 已全部处理

        # 从 idx 往列表头方向处理
        target = msgs[:idx] if idx > 0 else msgs
        for msg_id, text, create_time, sender_name in reversed(target):
            self._process_one_message(c, msg_id, text, create_time, sender_name, state)
            state.last_msg_id = msg_id

    def _poll_new_message(self, c: Candidate, state: _SessionState
                          ) -> Optional[tuple[str, str, str, str]]:
        """检查 sender 是否有新消息（比 state.last_msg_id 更新）

        Returns:
            (msg_id, text, create_time, sender_name) 或 None
        """
        table = self._mgr.snapshot()
        msgs = table.get(c.sender_id, [])
        if not msgs:
            return None

        # msgs 是 newest-first
        if not state.last_msg_id:
            return None  # 已经在 _process_existing 处理完了全部

        try:
            idx = next(i for i, (mid, _, _, _) in enumerate(msgs)
                       if mid == state.last_msg_id)
        except StopIteration:
            return None

        if idx == 0:
            return None  # 没有更新的消息

        # idx-1 是比 last_msg_id 更新的消息中最旧的那条
        msg_id, text, create_time, sender_name = msgs[idx - 1]
        return (msg_id, text, create_time, sender_name)

    def _process_one_message(self, c: Candidate, msg_id: str, text: str,
                             create_time: str, sender_name: str,
                             state: Optional[_SessionState] = None):
        """处理单条消息：回复"看到了" → 标记 Done → 更新 last_processed

        Args:
            state: 传入后同步更新运行时 last_msg_id，防止重复处理
        """
        log_msg = f"💬 {sender_name}: {text[:50]}{'...' if len(text) > 50 else ''}"
        _log_line(log_msg, c, self._log_file)

        token = self._token_provider.get()
        if not token:
            _log_line("⚠️  无 token，跳过回复", c, self._log_file)
            return

        reply_text = "看到了"
        reply_result = self._mgr.send_text(c.sender_id, reply_text)
        if reply_result.get("code") != 0:
            _log_line(f"⚠️  回复 {sender_name} 失败: {reply_result.get('msg', '')}", c, self._log_file)
        else:
            preview = reply_text[:10].replace("\n", " ")
            _log_line(f"✅  回复 {sender_name}: {preview}... [{len(reply_text)}chars]", c, self._log_file)

        # 2. 标记 Done
        done_result = self._mgr.react(msg_id, emoji="Done")
        if done_result.get("code") != 0:
            _log_line(f"⚠️  Done 标记失败: {done_result.get('msg', '')}", c, self._log_file)

        # 3. 更新 last_processed（持久化 + 运行时状态）
        lp = _load_last_processed(self._config)
        lp[c.sender_id] = msg_id
        _save_last_processed(self._config, lp)

        if state is not None:
            state.last_msg_id = msg_id

        self._result.message_count += 1
