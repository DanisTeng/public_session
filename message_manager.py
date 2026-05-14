"""message_manager.py - Feishu WS listener with simple message dispatch.

Functionality:
  - WS long connection: receives messages and dispatches via callback
  - REST: send_text(open_id, text), react(message_id, emoji)
  - No internal message cache. The consumer owns all state.
"""

import json
import logging
import threading
import time
from typing import Callable, Optional

from util.feishu import get_token, send_text_message, _request, react_message

logger = logging.getLogger("message_manager")


# ── Tiny data container ───────────────────────────────────────────────

class Message:
    """Minimal Feishu message. Just what the consumer needs."""

    __slots__ = ("message_id", "sender_id", "text", "create_time")

    def __init__(self, message_id: str, sender_id: str, text: str, create_time: str = "0"):
        self.message_id = message_id
        self.sender_id = sender_id
        self.text = text
        self.create_time = create_time

    def __repr__(self):
        return f"Message(id={self.message_id[:18]}, sender={self.sender_id[:12]}, text={self.text[:30]})"


# ── MessageManager ────────────────────────────────────────────────────

class MessageManager:
    """Feishu message manager.

    - Starts a background WS thread that receives messages.
    - Each incoming message is dispatched to a user-supplied callback.
    - Provides send_text / react helpers for the consumer to use.

    Usage:
        def on_msg(msg):
            print(f"Got: {msg.text} from {msg.sender_id}")

        mgr = MessageManager(app_id, app_secret, on_message=on_msg)
        mgr.start()
        # ...
        mgr.send_text("ou_xxx", "hello")
        mgr.stop()
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        on_message: Optional[Callable[[Message], None]] = None,
    ):
        self._app_id = app_id
        self._app_secret = app_secret
        self._on_message = on_message
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
        """Extract plain text from a message object."""
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
            event_handler=handler, log_level=lark.LogLevel.WARN,
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

        msg = Message(
            message_id=message_id,
            sender_id=sender_id,
            text=text,
            create_time=create_time,
        )

        if self._on_message:
            try:
                self._on_message(msg)
            except Exception as e:
                logger.error(f"on_message callback failed: {e}")
