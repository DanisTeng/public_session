#!/usr/bin/env python3
"""
test_message_manager.py — MessageManager integration test.

Usage:
  1. Set PUBLIC_FEISHU_APP_ID and PUBLIC_FEISHU_APP_SECRET
  2. python3 test_message_manager.py
  3. Send a private chat message to your james_pm bot on Feishu
  4. Program prints the received message and exits

Expected output:
  [12:00:00] MessageManager started
  [12:00:05] [callback] Got: hello from ou_xxx...
  [12:00:05] [callback] react result: {...}
  [12:00:05] Test complete. Exiting.
"""

import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from message_manager import MessageManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger("test")

APP_ID = os.environ.get("PUBLIC_FEISHU_APP_ID")
APP_SECRET = os.environ.get("PUBLIC_FEISHU_APP_SECRET")

if not APP_ID or not APP_SECRET:
    print("❌  Please set PUBLIC_FEISHU_APP_ID and PUBLIC_FEISHU_APP_SECRET")
    sys.exit(1)


def main():
    logger.info("🚀  Starting MessageManager test...")

    received = threading.Event()
    msg_text = [""]

    def on_msg(msg):
        logger.info(f"[callback] Got: {msg.text} from {msg.sender_id}")
        msg_text[0] = msg.text

        # send a reply
        result = mgr.send_text(msg.sender_id, f"收到: {msg.text}")
        logger.info(f"[callback] send result: code={result.get('code')}")

        # react with Done
        result2 = mgr.react(msg.message_id, emoji="Done")
        logger.info(f"[callback] react result: code={result2.get('code')}")

        received.set()

    import threading

    mgr = MessageManager(APP_ID, APP_SECRET, on_message=on_msg)
    mgr.start()

    logger.info("⏳  Please send a private message to james_pm bot on Feishu now")
    logger.info("")

    if received.wait(timeout=90):
        logger.info(f"✅  Received: {msg_text[0]}")
    else:
        logger.warning("⚠️  No message received within 90s")

    mgr.stop()
    logger.info("👋  Done")


if __name__ == "__main__":
    main()
