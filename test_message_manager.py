#!/usr/bin/env python3
"""
test_message_manager.py — MessageManager 集成测试

使用方法：
  1. 确保 PUBLIC_FEISHU_APP_ID 和 PUBLIC_FEISHU_APP_SECRET 已设置
  2. 启动测试：python3 test_message_manager.py
  3. 此时程序会启动 WS 长连接，并向飞书 bot 账号发送消息
  4. 请给你（james_pm bot）发一条飞书私聊消息
  5. 程序收到消息后会在终端打印，然后退出
  6. 按 Ctrl+C 也可手动退出

预期输出：
  [17:15:00] MessageManager started (WS thread)
  [17:15:00] WS client created, starting long connection...
  ...
  [17:15:05] WS received: [oc_xxx…] ou_xxx: 你的消息内容
  [17:15:05] Snapshot captured: MessageHistoryTable(1 chats, 1 messages)
  [17:15:05] Chat IDs: ['oc_xxx']
  [17:15:05] Messages in chat: ...
  [17:15:05] Test complete. Exiting.
"""

import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from message_manager import MessageManager

# 配置日志
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

    # 1. 创建并启动 MessageManager
    mgr = MessageManager(APP_ID, APP_SECRET)
    mgr.start()

    # 2. 等待 WS 连接建立 + 等待收到消息
    logger.info("⏳  Waiting for incoming messages...")
    logger.info("")
    logger.info("============================================================")
    logger.info("  请现在给你的 james_pm bot（PUBLIC bot）发一条飞书私聊消息")
    logger.info("  收到消息后本程序会在 5 秒内自动退出")
    logger.info("============================================================")
    logger.info("")

    timeout = 60  # 最多等 60 秒
    start = time.time()
    captured = False

    try:
        while time.time() - start < timeout:
            # 3. 每隔 1 秒获取一次快照
            snap = mgr.snapshot()
            chat_ids = snap.get_all_chat_ids()
            if chat_ids:
                logger.info(f"📸  Snapshot captured: {snap}")
                logger.info(f"📋  Chat IDs: {chat_ids}")
                for cid in chat_ids:
                    msgs = snap.get_chat_messages(cid, limit=5)
                    logger.info(f"📝  Messages in {cid[:16]}... ({len(msgs)}):")
                    for m in msgs:
                        logger.info(f"     [{m.message_id[:16]}…] {m.text[:80]}")
                captured = True
                break
            time.sleep(1)

        if not captured:
            logger.warning("⚠️  No messages received within 60s timeout")
        else:
            logger.info("✅  Test complete. Exiting.")

    except KeyboardInterrupt:
        logger.info("🛑  Interrupted by user")
    finally:
        mgr.stop()
        logger.info("👋  Done")


if __name__ == "__main__":
    main()
