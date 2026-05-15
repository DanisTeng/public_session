"""message_manager.py - Feishu WS listener + message snapshot.

Functionality:
  - WS long connection: receives messages, stores in internal table
  - snapshot(): thread-safe deep copy of all messages (for OneTick polling)
  - NameResolver: lazy-cached open_id → name mapping via contact API
  - on_message callback (optional, for event-driven consumers)
  - REST: send_text(open_id, text), react(message_id, emoji)
"""

import copy
import json
import logging
import threading
import time
from typing import Callable, Optional

from util.feishu import get_token, send_text_message, _request, react_message

logger = logging.getLogger("message_manager")


# ── NameResolver ────────────────────────────────────────────────────────

class NameResolver:
    """Lazy-cached open_id → name mapping.

    通过飞书 contact API 查询用户名字，结果永久缓存（名字不会频繁变化）。
    线程安全，支持并发查询。
    """

    def __init__(self, app_id: str, app_secret: str):
        self._app_id = app_id
        self._app_secret = app_secret
        self._cache: dict[str, str] = {}
        self._lock = threading.Lock()

    def resolve(self, open_id: str) -> Optional[str]:
        """获取 open_id 对应的用户名字。

        优先返回缓存结果。缓存未命中时调用 contact API 查询。
        解析失败（API 不可用、名字不存在）时返回 None。

        Args:
            open_id: 飞书用户的 open_id

        Returns:
            用户名字（中文名），或 None（解析失败）
        """
        with self._lock:
            cached = self._cache.get(open_id)
            if cached is not None:
                return cached if cached else None

        token = get_token(self._app_id, self._app_secret)
        if not token:
            return None

        result = _request(f"/contact/v3/users/{open_id}", token)
        user = result.get("data", {}).get("user", {})
        name = user.get("name", "") or ""

        with self._lock:
            # 缓存结果：空字符串表示已查询过但无名字
            self._cache[open_id] = name

        return name if name else None

    def cached_name(self, open_id: str) -> Optional[str]:
        """仅返回缓存中的名字，不触发 API 调用。

        Args:
            open_id: 飞书用户的 open_id

        Returns:
            缓存的名字，或 None（未缓存）
        """
        with self._lock:
            return self._cache.get(open_id)


# ── Message ───────────────────────────────────────────────────────────

class Message:
    """Minimal Feishu message."""

    __slots__ = ("message_id", "sender_id", "sender_name", "text", "create_time")

    def __init__(self, message_id: str, sender_id: str, sender_name: str,
                 text: str, create_time: str = "0"):
        self.message_id = message_id
        self.sender_id = sender_id
        self.sender_name = sender_name
        self.text = text
        self.create_time = create_time

    def __repr__(self):
        return (f"Message(id={self.message_id[:18]}, "
                f"sender={self.sender_name}({self.sender_id[:12]}), "
                f"text={self.text[:30]})")


# ── MessageTable ──────────────────────────────────────────────────────

class MessageTable:
    """Thread-safe message store.

    Messages grouped by sender_id (open_id). Each sender gets a list
    of (message_id, text, create_time, sender_name) tuples, newest first.

    Consumer reads via deep-copy snapshot. No dedup — WS won't deliver
    the same message twice.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._by_sender: dict[str, list[tuple[str, str, str, str]]] = {}

    def add(self, message_id: str, sender_id: str, text: str, create_time: str,
            sender_name: str):
        with self._lock:
            if sender_id not in self._by_sender:
                self._by_sender[sender_id] = []
            self._by_sender[sender_id].insert(0,
                (message_id, text, create_time, sender_name))

    def snapshot(self) -> dict[str, list[tuple[str, str, str, str]]]:
        """Deep copy of {sender_id: [(msg_id, text, time, name), ...]}, newest first."""
        with self._lock:
            return copy.deepcopy(self._by_sender)


# ── MessageManager ────────────────────────────────────────────────────

class MessageManager:
    """Feishu message manager.

    - WS background thread receives and stores messages in MessageTable.
    - snapshot() for OneTick polling (thread-safe deep copy).
    - NameResolver built-in: automatically resolves sender names via contact API.
    - on_message callback for event-driven consumers (optional).
    - send_text / react helpers.

    Usage:
        mgr = MessageManager(app_id, app_secret)
        mgr.start()
        ...
        table = mgr.snapshot()  # OneTick polling
        send_text("ou_xxx", "hello")
        mgr.stop()
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        on_message: Optional[Callable[[Message], None]] = None,
        mark_get_on_receive: bool = False,
    ):
        self._app_id = app_id
        self._app_secret = app_secret
        self._table = MessageTable()
        self._name_resolver = NameResolver(app_id, app_secret)
        self._on_message = on_message
        self._mark_get_on_receive = mark_get_on_receive
        self._ws_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # ── lifecycle ──

    def start(self):
        if self._ws_thread and self._ws_thread.is_alive():
            logger.warning("MessageManager already running")
            return
        self._stop_event.clear()
        self._ws_thread = threading.Thread(
            target=self._ws_loop, name="msg-mgr-ws", daemon=True,
        )
        self._ws_thread.start()
        logger.info("MessageManager started")

    def stop(self):
        self._stop_event.set()
        if self._ws_thread and self._ws_thread.is_alive():
            self._ws_thread.join(timeout=10)
        logger.info("MessageManager stopped")

    # ── name resolver (public) ──

    def resolve_name(self, open_id: str) -> Optional[str]:
        """获取 open_id 对应的用户名字。

        委托给内置的 NameResolver，首次调用自动缓存。

        Returns:
            用户名字（中文名），或 None（解析失败）
        """
        return self._name_resolver.resolve(open_id)

    # ── snapshot (thread-safe) ──

    def snapshot(self) -> dict[str, list[tuple[str, str, str, str]]]:
        """Thread-safe deep copy of all messages.

        Returns:
            {sender_id: [(message_id, text, create_time, sender_name), ...]}
            Each list is newest-first.
        """
        return self._table.snapshot()

    # ── REST helpers ──

    def send_text(self, open_id: str, text: str) -> dict:
        token = get_token(self._app_id, self._app_secret)
        if not token:
            return {"code": -1, "msg": "token failed"}
        return send_text_message(open_id, token, text)

    def send_text_to_chat(self, chat_id: str, text: str) -> dict:
        content = json.dumps({"text": text})
        token = get_token(self._app_id, self._app_secret)
        if not token:
            return {"code": -1, "msg": "token failed"}
        return _request(
            "/im/v1/messages?receive_id_type=chat_id",
            token=token,
            method="POST",
            body={"receive_id": chat_id, "msg_type": "text", "content": content},
        )

    def react(self, message_id: str, emoji: str = "Done") -> dict:
        token = get_token(self._app_id, self._app_secret)
        if not token:
            return {"code": -1, "msg": "token failed"}
        return react_message(message_id, token, emoji=emoji)

    # ── WS loop ──

    @staticmethod
    def _extract_text(msg_obj) -> str:
        body = getattr(msg_obj, 'body', None)
        if not body:
            return ""
        content = getattr(body, 'content', '')
        if not content:
            return ""
        try:
            return json.loads(content).get("text", str(content))
        except (json.JSONDecodeError, TypeError):
            return str(content)

    def _ws_loop(self):
        try:
            import lark_oapi as lark
            from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
        except ImportError:
            logger.error("lark-oapi not installed, run: pip install lark-oapi")
            return

        handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_ws_message)
            .build()
        )

        ws_client = lark.ws.Client(
            self._app_id, self._app_secret,
            event_handler=handler, log_level=lark.LogLevel.WARNING,
        )

        while not self._stop_event.is_set():
            try:
                ws_client.start()
            except Exception as e:
                if self._stop_event.is_set():
                    break
                logger.warning(f"WS lost ({e}), reconnecting in 5s...")
                time.sleep(5)

    def _on_ws_message(self, data: "P2ImMessageReceiveV1") -> None:
        event = data.event
        if not event or not event.message:
            return

        msg_obj = event.message
        message_id = getattr(msg_obj, 'message_id', '')
        if not message_id:
            return

        # sender 信息在 event.sender 上，不在 message.sender 里
        event_sender = getattr(event, 'sender', None)
        sender_id = ''
        if event_sender:
            sender_id_obj = getattr(event_sender, 'sender_id', None)
            if sender_id_obj is not None:
                sender_id = getattr(sender_id_obj, 'open_id', '') or ''

        if not sender_id:
            logger.error(
                f"Dropping msg {message_id[:18]}: empty sender_id. "
                f"event.sender={event_sender!r}"
            )
            return

        text = self._extract_text(msg_obj)
        create_time = getattr(msg_obj, 'create_time', '0')

        sender_name = self._name_resolver.resolve(sender_id)
        if not sender_name:
            logger.error(
                f"Dropping msg {message_id[:18]}: name resolve failed. "
                f"sender_id={sender_id[:24]}"
            )
            return

        msg = Message(message_id, sender_id, sender_name, text, create_time)

        self._table.add(message_id, sender_id, text, create_time, sender_name)

        # optional callback for event-driven consumers
        # auto-reply with Get reaction when enabled
        if self._mark_get_on_receive:
            try:
                self.react(message_id, emoji="Get")
            except Exception as e:
                logger.error(f"auto Get reaction failed: {e}")

        if self._on_message:
            try:
                self._on_message(msg)
            except Exception as e:
                logger.error(f"on_message callback failed: {e}")
