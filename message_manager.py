"""message_manager.py - Feishu WS listener + message snapshot.

Functionality:
  - WS long connection: receives messages, stores in internal table
  - snapshot(): thread-safe deep copy of all messages (for OneTick polling)
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


# ── Message ───────────────────────────────────────────────────────────

class Message:
    """Minimal Feishu message."""

    __slots__ = ("message_id", "sender_id", "text", "create_time")

    def __init__(self, message_id: str, sender_id: str, text: str, create_time: str = "0"):
        self.message_id = message_id
        self.sender_id = sender_id
        self.text = text
        self.create_time = create_time

    def __repr__(self):
        return f"Message(id={self.message_id[:18]}, sender={self.sender_id[:12]}, text={self.text[:30]})"


# ── MessageTable ──────────────────────────────────────────────────────

class MessageTable:
    """Thread-safe message store.

    Messages grouped by sender_id (open_id). Each sender gets a list
    of (message_id, text, create_time) tuples, newest first.

    Consumer reads via deep-copy snapshot. No dedup — WS won't deliver
    the same message twice.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._by_sender: dict[str, list[tuple[str, str, str]]] = {}

    def add(self, message_id: str, sender_id: str, text: str, create_time: str):
        with self._lock:
            if sender_id not in self._by_sender:
                self._by_sender[sender_id] = []
            self._by_sender[sender_id].insert(0, (message_id, text, create_time))

    def snapshot(self) -> dict[str, list[tuple[str, str, str]]]:
        """Deep copy of {sender_id: [(msg_id, text, time), ...]}, newest first."""
        with self._lock:
            return copy.deepcopy(self._by_sender)


# ── MessageManager ────────────────────────────────────────────────────

class MessageManager:
    """Feishu message manager.

    - WS background thread receives and stores messages in MessageTable.
    - snapshot() for OneTick polling (thread-safe deep copy).
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

    # ── snapshot (thread-safe) ──

    def snapshot(self) -> dict[str, list[tuple[str, str, str]]]:
        """Thread-safe deep copy of all messages.

        Returns:
            {sender_id: [(message_id, text, create_time), ...]}
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

        sender = getattr(msg_obj, 'sender', None)
        sender_id = str(getattr(sender, 'id', '')) if sender else ''

        text = self._extract_text(msg_obj)
        create_time = getattr(msg_obj, 'create_time', '0')

        msg = Message(message_id, sender_id, text, create_time)

        # always store in table
        self._table.add(message_id, sender_id, text, create_time)

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
