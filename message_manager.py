"""
message_manager.py — 飞书消息收发与管理

MessageManager：飞书客户端封装，负责：
  - 通过 WS 长连接实时接收新消息
  - 通过 REST API 发消息
  - 在本地维护 MessageHistoryTable（按聊天对象缓存最近 N 条消息）
  - 提供线程安全的快照拷贝接口供 OneTick 消费

MessageHistoryTable：消息缓存表，按 chat_id 组织。
  每条缓存的 Message 包含：message_id, chat_id, sender 信息, 文本内容, create_time 等。

用法：
  manager = MessageManager(config)
  manager.start()       # 后台线程启动 WS 长连接
  snapshot = manager.snapshot()  # OneTick 中获取快照（线程安全，拷贝时 cache 被锁）
  manager.stop()        # 关闭 WS 连接
"""

import copy
import json
import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger("message_manager")

HKT = timezone(timedelta(hours=8))

# ── 消息缓存上限 ──────────────────────────────────────────────────────
MAX_MESSAGES_PER_CHAT = 50  # 每个聊天对象最多缓存 50 条


# ── Message 数据结构 ───────────────────────────────────────────────────

class Message:
    """单条飞书消息的封装"""

    __slots__ = (
        "message_id", "chat_id", "chat_type",
        "sender_id", "sender_type",
        "text", "raw_content",
        "msg_type", "create_time",
    )

    def __init__(self, raw: dict):
        """
        Args:
            raw: 飞书消息事件的原始 JSON dict，或 list_messages API 返回的 item
        """
        self.message_id = raw.get("message_id", "") or raw.get("message_id", "")
        self.chat_id = raw.get("chat_id", "")
        self.chat_type = raw.get("chat_type", "p2p")  # p2p | group

        sender = raw.get("sender", {})
        if sender:
            self.sender_id = sender.get("id", "") or sender.get("sender_id", "")
            self.sender_type = sender.get("sender_type", "user")
        else:
            self.sender_id = ""
            self.sender_type = "user"

        self.msg_type = raw.get("msg_type", "text")
        self.create_time = raw.get("create_time", "0")

        # 统一提取文本内容
        self.raw_content = raw.get("body", {}).get("content", "")
        content_str = raw.get("content", "")
        # content 可能是 JSON 字符串 {"text": "xxx"}
        if content_str:
            try:
                parsed = json.loads(content_str)
                self.text = parsed.get("text", content_str)
            except (json.JSONDecodeError, TypeError):
                self.text = content_str
        elif self.raw_content:
            try:
                parsed = json.loads(self.raw_content)
                self.text = parsed.get("text", self.raw_content)
            except (json.JSONDecodeError, TypeError):
                self.text = self.raw_content
        else:
            self.text = ""

    def __repr__(self):
        return (f"Message(id={self.message_id[:20]}..., "
                f"chat={self.chat_id[:12]}..., "
                f"sender={self.sender_id[:12]}..., "
                f"text={self.text[:30]})")


# ── MessageHistoryTable ────────────────────────────────────────────────

class MessageHistoryTable:
    """消息历史缓存表

    按 chat_id 组织，每个 chat_id 保留最近的 MAX_MESSAGES_PER_CHAT 条消息。
    新消息插入到列表头部（最新在前）。
    """

    def __init__(self):
        # chat_id -> list[Message] (index 0 = 最新)
        self._chats: dict[str, list[Message]] = {}

    def add_message(self, msg: Message):
        """插入一条消息到对应 chat 的缓存头部

        如果已存在相同 message_id，跳过不重复插入。
        """
        chat_id = msg.chat_id
        if chat_id not in self._chats:
            self._chats[chat_id] = []
        msgs = self._chats[chat_id]

        # 去重
        for existing in msgs:
            if existing.message_id == msg.message_id:
                return

        msgs.insert(0, msg)
        # 裁剪超出的部分
        if len(msgs) > MAX_MESSAGES_PER_CHAT:
            self._chats[chat_id] = msgs[:MAX_MESSAGES_PER_CHAT]

    def get_chat_messages(self, chat_id: str, limit: int = 20) -> list[Message]:
        """获取指定 chat 的最新 N 条消息（副本，线程安全）"""
        msgs = self._chats.get(chat_id, [])
        return copy.deepcopy(msgs[:limit])

    def get_all_chat_ids(self) -> list[str]:
        """返回所有有缓存的 chat_id 列表（副本）"""
        return list(self._chats.keys())

    def get_message_count(self, chat_id: str) -> int:
        """返回指定 chat 的缓存消息数"""
        return len(self._chats.get(chat_id, []))

    def __repr__(self):
        total = sum(len(v) for v in self._chats.values())
        return (f"MessageHistoryTable({len(self._chats)} chats, "
                f"{total} messages)")


# ── MessageManager ─────────────────────────────────────────────────────

class MessageManager:
    """飞书消息管理器

    职责：
      1. WS 长连接实时监听新消息，写入 MessageHistoryTable
      2. REST API 主动发消息
      3. 对外提供线程安全的快照接口（OneTick 消费时加锁）

    用法：
      mgr = MessageManager(app_id, app_secret)
      mgr.start()
      # ...
      snapshot = mgr.snapshot()   # 线程安全快照
      # ...
      mgr.stop()
    """

    def __init__(self, app_id: str, app_secret: str):
        self._app_id = app_id
        self._app_secret = app_secret
        self._table = MessageHistoryTable()
        self._lock = threading.Lock()
        self._ws_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False

    # ── 启动/停止 ──

    def start(self):
        """启动 WS 长连接后台线程

        WS 线程持续运行，收到新消息时自动写入 MessageHistoryTable。
        如果 WS 连接断开，自动重连（lark-oapi SDK 自带重连机制）。
        """
        if self._running:
            logger.warning("MessageManager already running")
            return
        self._running = True
        self._stop_event.clear()

        self._ws_thread = threading.Thread(
            target=self._ws_loop,
            name="message-manager-ws",
            daemon=True,
        )
        self._ws_thread.start()
        logger.info("MessageManager started (WS thread)")

    def stop(self):
        """停止 WS 长连接，等待线程退出"""
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._ws_thread and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=10)
        logger.info("MessageManager stopped")

    # ── 快照接口（线程安全） ──

    def snapshot(self) -> MessageHistoryTable:
        """获取 MessageHistoryTable 的深拷贝

        OneTick 调用此接口时，会锁住 cache 阻止 WS 线程写入。
        拷贝完成后立即释放锁。

        Returns:
            MessageHistoryTable: 当前 cache 的完整深拷贝
        """
        with self._lock:
            return copy.deepcopy(self._table)

    # ── 发送消息（REST API） ──

    def send_text(self, open_id: str, text: str) -> dict:
        """发送文本消息（使用 REST API，非 WS）

        Args:
            open_id: 接收者的 open_id (ou_xxx)
            text: 文本内容

        Returns:
            dict: 飞书 API 响应
        """
        from util.feishu import get_token, send_text_message

        token = get_token(self._app_id, self._app_secret)
        if not token:
            logger.error("send_text: failed to get token")
            return {"code": -1, "msg": "token failed"}
        result = send_text_message(open_id, token, text)
        return result

    def send_text_to_chat(self, chat_id: str, text: str) -> dict:
        """发送文本消息到指定会话

        Args:
            chat_id: 会话 ID (oc_xxx)
            text: 文本内容
        """
        content = json.dumps({"text": text})
        from util.feishu import _request, get_token

        token = get_token(self._app_id, self._app_secret)
        if not token:
            return {"code": -1, "msg": "token failed"}
        return _request(
            "/im/v1/messages?receive_id_type=chat_id",
            token=token,
            method="POST",
            body={
                "receive_id": chat_id,
                "msg_type": "text",
                "content": content,
            },
        )

    # ── WS 线程内部 ──

    def _ws_loop(self):
        """WS 长连接线程主循环

        使用 lark-oapi SDK 建立长连接，监听 P2P 消息事件。
        收到新消息时写入 MessageHistoryTable。
        断连时 SDK 会自动重连。
        """
        try:
            import lark_oapi as lark
            from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
        except ImportError:
            logger.error(
                "lark-oapi not installed. "
                "Run: pip install lark-oapi"
            )
            return

        # ── 注册事件处理器 ──
        def on_message(data: P2ImMessageReceiveV1) -> None:
            """WS 收到新消息时的回调

            将消息解析为 Message 对象，写入 MessageHistoryTable。
            """
            event = data.event
            if not event or not event.message:
                return

            msg = Message(event.message.__dict__ if hasattr(event.message, '__dict__') else {})
            # 补充 event 层的字段
            if hasattr(event.message, 'chat_id') and not msg.chat_id:
                msg.chat_id = getattr(event.message, 'chat_id', '')
            if hasattr(event.message, 'chat_type') and not msg.chat_type:
                msg.chat_type = getattr(event.message, 'chat_type', 'p2p')
            if hasattr(event.message, 'message_id') and not msg.message_id:
                msg.message_id = getattr(event.message, 'message_id', '')

            if not msg.message_id:
                return

            with self._lock:
                self._table.add_message(msg)

                ts = datetime.now(HKT).strftime("%H:%M:%S")
                sender_label = msg.sender_id[:12] if msg.sender_id else "?"
                logger.info(
                    f"[{ts}] WS received: [{msg.chat_id[:12]}…] "
                    f"{sender_label}: {msg.text[:60]}"
                )

        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(on_message)
            .build()
        )

        # ── 创建 WS Client ──
        ws_client = lark.ws.Client(
            self._app_id,
            self._app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )

        logger.info("WS client created, starting long connection...")

        # ── 持续运行直到 stop ──
        # lark.ws.Client.start() 是阻塞的
        # 通过 stop_event 包装，在主循环中检查退出
        while not self._stop_event.is_set():
            try:
                ws_client.start()
            except Exception as e:
                if self._stop_event.is_set():
                    break
                logger.warning(f"WS connection lost ({e}), reconnecting in 5s...")
                time.sleep(5)
                continue
            break  # start() 正常返回说明连接结束

        logger.info("WS loop exited")
