#!/bin/bash
# public_session.sh - 社会通道消息收发工具
# 依赖环境变量: PUBLIC_FEISHU_APP_ID, PUBLIC_FEISHU_APP_SECRET
#
# 用法:
#   ./public_session.sh get-token
#   ./public_session.sh send-msg <open_id> <text>
#   ./public_session.sh send-file <open_id> <file_path>
#   ./public_session.sh send-image <open_id> <image_path>
#   ./public_session.sh reply-msg <message_id> <text>
#   ./public_session.sh react-msg <message_id> [emoji]
#   ./public_session.sh get-reactions <message_id>
#   ./public_session.sh list-msgs <chat_id> [page_size]
#   ./public_session.sh get-msgs <chat_id> [page_size]
#   ./public_session.sh get-chat <open_id>

set -euo pipefail

APP_ID="${PUBLIC_FEISHU_APP_ID:?PUBLIC_FEISHU_APP_ID not set}"
APP_SECRET="${PUBLIC_FEISHU_APP_SECRET:?PUBLIC_FEISHU_APP_SECRET not set}"

get_token() {
  curl -s -X POST 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal' \
    -H 'Content-Type: application/json' \
    -d "{\"app_id\":\"${APP_ID}\",\"app_secret\":\"${APP_SECRET}\"}" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tenant_access_token",""))'
}

case "${1:-help}" in
  get-token)
    TOKEN=$(get_token)
    echo "$TOKEN"
    ;;

  send-msg)
    RECEIVE_ID="${2:?Usage: $0 send-msg <open_id> <text>}"
    MESSAGE_TEXT="${3:?Usage: $0 send-msg <open_id> <text>}"
    TOKEN=$(get_token)
    RESP=$(curl -s -X POST 'https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id' \
      -H "Authorization: Bearer ${TOKEN}" \
      -H 'Content-Type: application/json' \
      -d "{
        \"receive_id\": \"${RECEIVE_ID}\",
        \"msg_type\": \"text\",
        \"content\": \"{\\\"text\\\":\\\"${MESSAGE_TEXT}\\\"}\"
      }")
    echo "$RESP" | python3 -c '
import json,sys
d = json.load(sys.stdin)
code = d.get("code", -1)
print(f"code={code}")
if code == 0:
    print("message_id:", d["data"]["message_id"])
    print("chat_id:", d["data"]["chat_id"])
else:
    print("error:", d.get("msg",""))
'
    ;;

  send-file)
    RECEIVE_ID="${2:?Usage: $0 send-file <open_id> <file_path>}"
    FILE_PATH="${3:?Usage: $0 send-file <open_id> <file_path>}"
    FILE_NAME=$(basename "$FILE_PATH")
    TOKEN=$(get_token)
    # 上传文件
    UPLOAD_RESP=$(curl -s -X POST 'https://open.feishu.cn/open-apis/im/v1/files' \
      -H "Authorization: Bearer ${TOKEN}" \
      -F "file_type=stream" \
      -F "file_name=${FILE_NAME}" \
      -F "file=@${FILE_PATH}")
    FILE_KEY=$(echo "$UPLOAD_RESP" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("data",{}).get("file_key",""))' 2>/dev/null || echo "")
    if [ -z "$FILE_KEY" ]; then
      echo "Upload failed:"
      echo "$UPLOAD_RESP" | python3 -m json.tool
      exit 1
    fi
    # 发送文件消息
    RESP=$(curl -s -X POST 'https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id' \
      -H "Authorization: Bearer ${TOKEN}" \
      -H 'Content-Type: application/json' \
      -d "{
        \"receive_id\": \"${RECEIVE_ID}\",
        \"msg_type\": \"file\",
        \"content\": \"{\\\"file_key\\\":\\\"${FILE_KEY}\\\"}\"
      }")
    echo "$RESP" | python3 -c '
import json,sys
d = json.load(sys.stdin)
code = d.get("code", -1)
print(f"code={code}")
if code == 0:
    print("message_id:", d["data"]["message_id"])
else:
    print("error:", d.get("msg",""))
'
    ;;

  send-image)
    RECEIVE_ID="${2:?Usage: $0 send-image <open_id> <image_path>}"
    IMAGE_PATH="${3:?Usage: $0 send-image <open_id> <image_path>}"
    TOKEN=$(get_token)
    # 上传图片
    UPLOAD_RESP=$(curl -s -X POST 'https://open.feishu.cn/open-apis/im/v1/images' \
      -H "Authorization: Bearer ${TOKEN}" \
      -F "image_type=message" \
      -F "image=@${IMAGE_PATH}")
    IMAGE_KEY=$(echo "$UPLOAD_RESP" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("data",{}).get("image_key",""))' 2>/dev/null || echo "")
    if [ -z "$IMAGE_KEY" ]; then
      echo "Upload failed:"
      echo "$UPLOAD_RESP" | python3 -m json.tool
      exit 1
    fi
    # 发送图片消息
    RESP=$(curl -s -X POST 'https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id' \
      -H "Authorization: Bearer ${TOKEN}" \
      -H 'Content-Type: application/json' \
      -d "{
        \"receive_id\": \"${RECEIVE_ID}\",
        \"msg_type\": \"image\",
        \"content\": \"{\\\"image_key\\\":\\\"${IMAGE_KEY}\\\"}\"
      }")
    echo "$RESP" | python3 -c '
import json,sys
d = json.load(sys.stdin)
code = d.get("code", -1)
print(f"code={code}")
if code == 0:
    print("message_id:", d["data"]["message_id"])
else:
    print("error:", d.get("msg",""))
'
    ;;

  reply-msg)
    MSG_ID="${2:?Usage: $0 reply-msg <message_id> <text>}"
    TEXT="${3:?Usage: $0 reply-msg <message_id> <text>}"
    TOKEN=$(get_token)
    RESP=$(curl -s -X POST "https://open.feishu.cn/open-apis/im/v1/messages/${MSG_ID}/reply" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H 'Content-Type: application/json' \
      -d "{
        \"content\": \"{\\\"text\\\":\\\"${TEXT}\\\"}\",
        \"msg_type\": \"text\"
      }")
    echo "$RESP" | python3 -c '
import json,sys
d = json.load(sys.stdin)
code = d.get("code", -1)
print(f"code={code}")
if code == 0:
    print("message_id:", d["data"]["message_id"])
else:
    print("error:", d.get("msg",""))
'
    ;;

  get-reactions)
    MSG_ID="${2:?Usage: $0 get-reactions <message_id>}"
    TOKEN=$(get_token)
    RESP=$(curl -s -X GET "https://open.feishu.cn/open-apis/im/v1/messages/${MSG_ID}/reactions?page_size=20" \
      -H "Authorization: Bearer ${TOKEN}")
    echo "$RESP" | python3 -c '
import json,sys
d = json.load(sys.stdin)
code = d.get("code", -1)
print(f"code={code}")
if code == 0:
    items = d["data"]["items"]
    print(f"reactions: {len(items)}")
    for r in items:
        op = r["operator"]
        emoji = r["reaction_type"]["emoji_type"]
        op_id = op["operator_id"][:20]
        op_type = op["operator_type"]
        print(f"  {emoji:12s} by {op_type:4s} {op_id}")
else:
    print("error:", d.get("msg",""))
'
    ;;

  react-msg)
    MSG_ID="${2:?Usage: $0 react-msg <message_id> <emoji_type>}"
    EMOJI="${3:-Get}"
    TOKEN=$(get_token)
    RESP=$(curl -s -X POST "https://open.feishu.cn/open-apis/im/v1/messages/${MSG_ID}/reactions" \
      -H "Authorization: Bearer ${TOKEN}" \
      -H 'Content-Type: application/json; charset=utf-8' \
      -d "{\"reaction_type\": {\"emoji_type\": \"${EMOJI}\"}}")
    echo "$RESP" | python3 -c '
import json,sys
d = json.load(sys.stdin)
code = d.get("code", -1)
print(f"code={code}")
if code == 0:
    print("reaction_id:", d["data"]["reaction_id"][:40])
else:
    print("error:", d.get("msg",""))
'
    ;;

  list-msgs|get-msgs)
    CHAT_ID="${2:?Usage: $0 list-msgs <chat_id> [page_size]}"
    PAGE_SIZE="${3:-20}"
    TOKEN=$(get_token)
    RESP=$(curl -s -X GET "https://open.feishu.cn/open-apis/im/v1/messages?container_id_type=chat&container_id=${CHAT_ID}&page_size=${PAGE_SIZE}&sort_type=ByCreateTimeDesc" \
      -H "Authorization: Bearer ${TOKEN}")
    echo "$RESP" | python3 -c '
import json,sys
d = json.load(sys.stdin)
code = d.get("code", -1)
if code != 0:
    print(f"Error: code={code} msg={d.get(\"msg\",\"\")}")
    sys.exit(1)
items = d["data"]["items"]
print(f"Total: {len(items)} messages")
for msg in reversed(items):
    sender = msg["sender"]["sender_type"]
    sender_id = msg["sender"]["id"]
    msg_type = msg["msg_type"]
    mid = msg["message_id"][:40]
    ts = msg["create_time"]
    # Extract content preview
    content = msg["body"]["content"]
    if msg_type == "text":
        preview = json.loads(content).get("text","")[:80]
    elif msg_type == "image":
        preview = f"[image: {json.loads(content).get(\"image_key\",\"\")[:30]}...]"
    elif msg_type == "file":
        preview = f"[file: {json.loads(content).get(\"file_name\",\"\")}]"
    else:
        preview = content[:60]
    print(f"  [{mid}] {sender}({sender_id[-12:]}) {msg_type}: {preview}")
'
    ;;

  get-chat)
    OPEN_ID="${2:?Usage: $0 get-chat <open_id>}"
    TOKEN=$(get_token)
    # 列出该用户的所有会话
    RESP=$(curl -s -X GET "https://open.feishu.cn/open-apis/im/v1/chats?page_size=20" \
      -H "Authorization: Bearer ${TOKEN}")
    echo "$RESP" | python3 -m json.tool
    ;;

  help|*)
    echo "Usage: $0 <command> [args]"
    echo ""
    echo "Commands:"
    echo "  get-token              Get tenant_access_token"
    echo "  send-msg <open_id> <text>   Send text message"
    echo "  send-file <open_id> <path>  Send file"
    echo "  send-image <open_id> <path> Send image"
    echo "  reply-msg <msg_id> <text>   Reply to a message"
    echo "  list-msgs <chat_id> [n]     List messages in a chat"
    echo "  get-chat <open_id>          Get chat info"
    echo ""
    echo "Environment:"
    echo "  PUBLIC_FEISHU_APP_ID"
    echo "  PUBLIC_FEISHU_APP_SECRET"
    ;;
esac
