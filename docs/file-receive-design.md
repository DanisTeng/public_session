# 收文件链路设计 (v2)

## 背景

当前 public_session SingleChatManager 仅支持文本消息交互。
用户通过飞书发送文件（图片、PDF、文档等）时，WS 推送的 `msg_type` 不再是 `text`。

## 设计原则

**文件是后台行为，不与对话流程交互。**

1. WS 收到 non-text 消息 → 解析 file_key → 同步下载到本地 → 结束
2. 不入 MessageTable，不触发 OneTick，不产生额外回复
3. Chat init 时告知 agent 文件存储路径，agent 自行决定是否需要翻看
4. 重复消息（同一 message_id）不重复下载

## 数据流

```
用户发文件 → WS → _on_ws_message
                       │
                       ▼
                 msg_type == "text"?
                       │
              ┌───是───┴───否───┐
              ▼                 ▼
       MessageTable.add()     _download_and_store_file()
              │                  │
              │              解析 file_key / image_key
              │                  │
              │              构造输出路径（含去重检查）
              │                  │
              │              同步下载 → 存到 received_files/
              │                  │
              │              日志记录（成功/失败）
              │                  │
              ▼                  ▼
        OneTick 消费        🎯 结束，没有表记录
```

## 存储路径

### 配置项

```json
{
  "file_storage_dir": "/james_pm/public_session/received_files"
}
```

未配置时默认：`state_dir/../received_files/`

### 目录结构

```
received_files/
  └── ou_xxx/                    # sender 的 open_id
      └── 2026-05-21/
          ├── om_xxx_xxx.pdf     # 文件名 = msg_id_原始文件名
          └── om_xxx_xxx.jpg     # image 消息 file_name = "unknown"
```

### 去重策略

下载前检查 `output_path` 是否已存在，存在则跳过（同一 message_id 不会重复处理）。

## 同步下载

- 调用 `download_resource()`（`util/feishu.py`）
- 超时 60 秒
- 大小检查 100MB

## Context 提示词

Chat init 时 `_build_context_prefix` 附加一段：

```
[文件存储] {name} 发送的文件已自动保存到本地，路径: {file_path}/
如有需要，可以读取这些文件来获取信息。
```

## 飞书 API

### 资源下载

```
GET https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/resources/{file_key}?type=file
Authorization: Bearer {tenant_access_token}
```

### non-text 消息 content 格式

| msg_type  | content 字段 |
|-----------|-------------|
| `file`    | `{"file_key": "xxx", "file_name": "xxx.pdf"}` |
| `image`   | `{"image_key": "xxx"}` |
| `media`   | `{"file_key": "xxx", "image_key": "xxx"}` |
| `audio`   | `{"file_key": "xxx"}` |
| `video`   | `{"file_key": "xxx"}` |

## 改动的文件

| 文件 | 改动 |
|------|------|
| `util/feishu.py` | 新增 `download_resource()` |
| `message_manager.py` | 新增文件下载逻辑、`file_storage_dir` 支持、非 text 消息走下载路径 |
| `config.py` | 新增 `file_storage_dir` 字段 |
| `config.json` | 新增 `file_storage_dir` 配置 |
| `public_session.py` | 传 `file_storage_dir` 给 MessageManager |
| `single_chat_manager.py` | `_build_context_prefix` 加文件路径提示 |

---

*设计版本: v2, 2026-05-21*
