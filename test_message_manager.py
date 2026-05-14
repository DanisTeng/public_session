#!/usr/bin/env python3
"""
test_message_manager.py — Integration test via snapshot polling.

Usage:
  1. Set PUBLIC_FEISHU_APP_ID and PUBLIC_FEISHU_APP_SECRET
  2. python3 test_message_manager.py
  3. Send a private chat message to james_pm bot on Feishu
  4. Program prints received message, sends a reply, reacts Done, exits
"""

import logging
import os
import sys
import threading
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
    logger.info("🚀  Starting MessageManager test (snapshot polling)...")

    mgr = MessageManager(APP_ID, APP_SECRET)
    mgr.start()

    logger.info("⏳  Send a private message to james_pm bot on Feishu now")
    logger.info("")

    timeout = 90
    start = time.time()
    found = None

    while time.time() - start < timeout:
        snap = mgr.snapshot()
        if snap:
            for sid, msgs in snap.items():
                found = (sid, msgs[0])
                break
        if found:
            break
        time.sleep(1)

    if found:
        sid, (msg_id, text, t) = found
        logger.info(f"✅  Received from {sid}: {text}")

        # reply
        result = mgr.send_text(sid, f"收到: {text}")
        logger.info(f"send_text result: code={result.get('code')}")

        # react
        result2 = mgr.react(msg_id, emoji="Done")
        logger.info(f"react result: code={result2.get('code')}")
    else:
        logger.warning("⚠️  No message received within 90s")

    mgr.stop()
    logger.info("👋  Done")


if __name__ == "__main__":
    main()
