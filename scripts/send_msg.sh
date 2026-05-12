#!/bin/bash
# send_msg.sh - 通过飞书 API 主动发送消息
# 用法: ./send_msg.sh <receive_id> <text>
# receive_id: 对方的 open_id (ou_xxx) 或 user_id
# rely on env FEISHU_APP_SECRET and config for app_id

set -euo pipefail

APP_ID="cli_a95045e84e78dbb5"
RECEIVE_ID="${1:?Usage: $0 <receive_id> <text>}"
MESSAGE_TEXT="${2:?Usage: $0 <receive_id> <text>}"

# 1. 获取 tenant_access_token
TOKEN=$(curl -s -X POST 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal' \
  -H 'Content-Type: application/json' \
  -d "{\"app_id\":\"${APP_ID}\",\"app_secret\":\"${FEISHU_APP_SECRET}\"}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tenant_access_token",""))')

if [ -z "$TOKEN" ]; then
  echo "ERROR: Failed to get tenant_access_token"
  exit 1
fi

# 2. 发送消息
# 使用 text 类型，receive_id_type 用 open_id
RESP=$(curl -s -X POST 'https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id' \
  -H "Authorization: Bearer ${TOKEN}" \
  -H 'Content-Type: application/json' \
  -d "{
    \"receive_id\": \"${RECEIVE_ID}\",
    \"msg_type\": \"text\",
    \"content\": \"{\\\"text\\\":\\\"${MESSAGE_TEXT}\\\"}\"
  }")

echo "$RESP" | python3 -m json.tool

# 检查是否成功
CODE=$(echo "$RESP" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("code", -1))')
if [ "$CODE" = "0" ]; then
  echo "SUCCESS: Message sent"
else
  echo "FAILED: code=$CODE"
fi
