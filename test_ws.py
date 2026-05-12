"""
test_ws.py — 验证飞书 lark-oapi WebSocket 事件推送

测试：
  1. 用 PUBLIC_FEISHU_APP_ID/APP_SECRET 连接飞书 WS
  2. 注册消息接收事件处理器
  3. 启动后持续运行，收到推送就打印

用法：
  export PUBLIC_FEISHU_APP_ID=xxx
  export PUBLIC_FEISHU_APP_SECRET=xxx
  python3 test_ws.py
"""

import json
import os
import sys

from lark_oapi import EventDispatcherHandler, LogLevel
from lark_oapi.ws import Client as WSClient

APP_ID = os.environ.get("PUBLIC_FEISHU_APP_ID")
APP_SECRET = os.environ.get("PUBLIC_FEISHU_APP_SECRET")
if not APP_ID or not APP_SECRET:
    print("❌  Set PUBLIC_FEISHU_APP_ID and PUBLIC_FEISHU_APP_SECRET")
    sys.exit(1)


def on_message(ctx, event):
    """收到新消息时的回调"""
    print(f"\n📩  New message received!")
    if event.event and event.event.message:
        msg = event.event.message
        print(f"  message_id: {msg.message_id}")
        print(f"  chat_id:    {msg.chat_id}")
        print(f"  msg_type:   {msg.msg_type}")
        if msg.sender:
            print(f"  sender_id:  {msg.sender.sender_id}")
        if msg.body and msg.body.content:
            try:
                content = json.loads(msg.body.content)
                if msg.msg_type == "text":
                    print(f"  content:    {content.get('text', '')[:100]}")
                elif msg.msg_type == "image":
                    print(f"  content:    [image: {content.get('image_key','')[:20]}...]")
                else:
                    print(f"  content:    {str(content)[:100]}")
            except json.JSONDecodeError:
                print(f"  content:    {msg.body.content[:100]}")
    else:
        print(f"  raw event: {event}")
    print()


def main():
    print("🚀  Connecting to Feishu WS...")
    print(f"  app_id: {APP_ID[:10]}...")

    handler = (
        EventDispatcherHandler.builder(APP_ID, APP_SECRET)
        .register_p2_im_message_receive_v1(on_message)
        .build()
    )

    client = WSClient(
        app_id=APP_ID,
        app_secret=APP_SECRET,
        log_level=LogLevel.INFO,
        event_handler=handler,
    )

    print("✅  WS client created, connecting...")
    print("⏳  Running (Ctrl+C to stop). Send a message to james_pm bot!")
    # start() 阻塞运行
    client.start()


if __name__ == "__main__":
    main()
