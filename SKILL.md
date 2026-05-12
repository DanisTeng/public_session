---
name: public-session
description: |
  Public social messaging channel via Feishu bot (REST API).
  Use when you need to: (1) Send text/file/image messages to Feishu users via a designated public bot, (2) Receive and read incoming messages from users, (3) Reply to messages to acknowledge receipt.
  NOT for: Document read/write (use feishu-doc), wiki operations (use feishu-wiki), Feishu drive operations (use feishu-drive), permission management (use feishu-perm).
---

# Public Session

社会通道：通过飞书 bot 身份与用户进行消息收发。

## 环境配置

依赖两个环境变量：

| 变量 | 用途 |
|------|------|
| `PUBLIC_FEISHU_APP_ID` | 社会通道飞书自建应用的 App ID |
| `PUBLIC_FEISHU_APP_SECRET` | 对应的 App Secret |

## 前提

- 飞书自建应用已开通：`im:message`、`im:resource`、`im:resource:upload`、`contact:contact:readonly` 权限
- 已知目标用户的 open_id（每个 bot 有独立 open_id 体系，需通过通讯录 API 查询）
- 首次发消息前用户须先与 bot 建立过会话（否则无法收发）

## 核心能力

### 1. 发送文本消息

```bash
scripts/public_session.sh send-msg <open_id> <text>
```

- `receive_id_type=open_id` — 用目标用户在该 bot 视角下的 open_id
- 返回 message_id 和 chat_id，可用于后续操作

### 2. 发送文件

两步：上传文件 → 发送文件消息

```bash
scripts/public_session.sh send-file <open_id> <file_path>
```

- 自动上传文件到飞书，获取 file_key，然后发送
- 支持任意文件类型（txt, pdf, png 等）

### 3. 发送图片

```bash
scripts/public_session.sh send-image <open_id> <image_path>
```

- 自动上传图片并发送

### 4. 添加 Get 表情（标记已读）

约定使用 `Get` 表情表示已读。

```bash
scripts/public_session.sh react-msg <message_id> Get
```

- 给用户发来的消息加 `Get` 表情，bot 在飞书端的"已读"信号
- 也可以读其他用户加的 emoji：`scripts/public_session.sh get-reactions <message_id>`
- 需要权限：`im:message.reactions:write_only`（加） + `im:message.reactions:read`（读）

### 5. 拉取会话消息

```bash
scripts/public_session.sh list-msgs <chat_id> [page_size]
```

- 按时间倒序排列消息
- 展示每条消息的 sender_type、msg_type、内容预览

### 6. 获取 token

```bash
scripts/public_session.sh get-token
```

- 用于手动调试或构造自定义 API 调用

## 通讯录查询

通过 `contact:contact:readonly` 权限查询用户信息：

```bash
# 获取 bot 所在租户的全部用户
curl -s -H "Authorization: Bearer <token>" \
  "https://open.feishu.cn/open-apis/contact/v3/users?page_size=50"
```

返回包含：name, open_id, union_id, avatar。注意 open_id 是针对该 bot 的（不同 bot 不同），union_id 是开发者维度统一的。

## 能力边界

| 能力 | 支持 | 说明 |
|------|------|------|
| 发送文本消息 | ✅ | 直接用 text msg_type |
| 发送文件 | ✅ | 先 POST /im/v1/files 上传，再发 file 消息 |
| 发送图片 | ✅ | 先 POST /im/v1/images 上传，再发 image 消息 |
| 发送富文本/卡片消息 | ⚠️ | 需要构造 msg_type=post 或 interactive，参考飞书文档 |
| 接收消息 | ✅ | GET /im/v1/messages 拉取指定会话的历史消息 |
| 回复消息 | ✅ | POST /messages/:id/reply |
| 标记已读（Get 表情） | ✅ | POST /messages/:id/reactions，用 `Get` 表情作为已读信号 |
| 查询自己发出消息的已读状态 | ✅ | GET /messages/:id/read_users（限7天内发出的消息） |
| 图片下载 | ⚠️ | 需要 im:resource 权限，用 GET /im/v1/images/:key |
| Fiexed 文件下载 | ⚠️ | 需要 im:resource 权限，用 GET /im/v1/files/:key |

## 常用场景

### 场景 1：给用户发送任务通知

```bash
OPEN_ID="ou_xxx"
scripts/public_session.sh send-msg "$OPEN_ID" "新任务：请完成模块A的测试"
```

### 场景 2：接收用户反馈并确认

```bash
# 先拉取消息
scripts/public_session.sh list-msgs "oc_xxx" 10

# 加 Get 表情标记已读
scripts/public_session.sh react-msg "om_xxx" Get

# 如需回复
scripts/public_session.sh reply-msg "om_xxx" "已收到，正在处理"
```

### 场景 3：发送报告文件

```bash
scripts/public_session.sh send-file "$OPEN_ID" "/tmp/report.pdf"
```

## 异步通信模式

PM 通过社会通道与 IC agents（或其他 bot）通信时，建议采用异步驱动模式：

1. PM 下任务：发消息给 IC，不等待回复
2. IC 工作：IC 在自己的 turn 里完成任务
3. IC 汇报：IC 写状态文件或主动发消息回 PM
4. PM 检查：PM 在下一轮 cron 中拉取未读消息、检查状态文件

避免正反馈震荡：PM 的每个 turn 只发消息不等待回复，下个 turn 再检查。

## 脚本文件

- `scripts/public_session.sh` — 主工具脚本
- `scripts/send_msg.sh` — 兼容旧版，单文件发送脚本
