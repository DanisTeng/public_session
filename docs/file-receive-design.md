# 收文件链路设计

## 背景

当前 public_session SingleChatManager 仅支持文本消息交互。
用户通过飞书发送文件（图片、PDF、文档等）时，WS 推送的 `msg_type` 不再是 `text`，
当前 `_extract_text` 对这些消息解析为空字符串，导致消息被当做无效消息丢弃。

## 目标

让 public_session 能完整处理收文件链路：
1. 收到 non-text 消息 → 解析文件信息
2. 同步下载文件到本地 → 存储路径可配置
3. 在 MessageTable 中记录为「系统消息」文本 → PPPC 可追溯
4. 下载失败时记录失败原因（尺寸超限、超时等）

## 术语

| 术语 | 说明 |
|------|------|
| 文件消息 | 飞书中 `msg_type` 非 `text` 的消息（file / image / media / audio / video 等），统称文件 |
| 系统消息 | Message 的 `msg_type == "system"`，是 message_manager 合成的消息，放置文本记录 |
| 文件存储 | 下载到本地的文件存放目录 |

## 数据流

```
用户 → WS → on_ws_message
                │
                ▼
         是文本消息？───是──→ 原流程（存 MessageTable，type=text）
                │
                否
                │
                ▼
          解析文件信息（file_key / image_key / file_name）
                │
                ▼
          同步下载文件到存储目录 ──成功──→ 存 MessageTable（type=system）
                │                          text: "[File: name=xxx.pdf, path=/james_pm/received/xxx.pdf]"
                │
                失败（超时/尺寸/其他）
                │
                ▼
          存 MessageTable（type=system）
           text: "[File: name=xxx.pdf, error=超出大小限制 (100MB)]"
```

下游消费（SingleChatManager）无变化：
- `pick_candidate` 从 snapshot 中正常选出 sender
- `_process_batch` 读到系统消息文本 → 传给 OpenClaw
- OpenClaw 回复中可直接引用文件路径
- PPPC 记录 `[File: ...]` 文本

## Message 结构扩展

当前 Message 类：

```python
class Message:
    __slots__ = ("message_id", "sender_id", "sender_name", "text",
                 "create_time", "recv_time")
    # msg_type: 当前只存 text，需增加
```

新增字段：

```python
class Message:
    __slots__ = ("message_id", "sender_id", "sender_name", "text",
                 "create_time", "recv_time", "msg_type")
```

`msg_type` 取值：
- `"text"` — 原始文本消息
- `"system"` — message_manager 合成的系统消息（含文件信息）

## 存储路径

### 配置项

新增 `Config.file_storage_dir`：

```json
{
  "file_storage_dir": "/james_pm/public_session/received_files"
}
```

默认行为：
- 未配置 → 使用 `$state_dir/../received_files/`

### 目录结构

```
received_files/
  └── ou_xxx/                    # sender 的 open_id
      └── 2026-05-21/
          ├── om_xxx_xxx.pdf     # 文件名 = msg_id_原始文件名
          └── om_xxx_xxx.jpg
```

## 同步下载策略

### 为什么同步

- 收文件是低频事件（每日几次，不太可能高频冲刷）
- 异步下载需要额外的线程/状态管理，复杂度大增
- 下载失败后的及时反馈简化（同在一个 callback 里处理）

### 超时

- 文件下载超时：60 秒
- 调用 `urllib.request` 设置 `timeout=60`

### 大小限制

- 飞书 API 限制：100 MB
- 下载前记录 Content-Length，超过此限制则直接返回失败

## 失败处理

| 失败类型 | text 记录格式 |
|----------|-------------|
| 大小超限 | `[File: name=xxx.pdf, error=超出大小限制 ({size}MB > 100MB)]` |
| 下载超时 | `[File: name=xxx.pdf, error=下载超时 (60s)]` |
| 网络错误 | `[File: name=xxx.pdf, error=网络错误: {msg}]` |
| 存储失败 | `[File: name=xxx.pdf, error=存储失败: {msg}]` |
| 解析失败 | `[File: error=无法解析文件消息: {raw_content}]` |

## 飞书 API 参考

### 资源下载

```
GET https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/resources/{file_key}?type=file
Authorization: Bearer {tenant_access_token}
```

响应：二进制流，通过 `Content-Disposition` 可以获取文件名。

### non-text 消息 content 格式

| msg_type  | content 字段 |
|-----------|-------------|
| `file`    | `{"file_key": "xxx", "file_name": "xxx.pdf"}` |
| `image`   | `{"image_key": "xxx"}` |
| `media`   | `{"file_key": "xxx", "image_key": "xxx"}` |
| `audio`   | `{"file_key": "xxx"}` |
| `video`   | `{"file_key": "xxx"}` |

## 需要的权限

当前 bot 已有 `im:message` 权限，需确认是否已包含资源下载：

| 权限 | 说明 | 是否已有 |
|------|------|---------|
| `im:message` | 基础消息能力 | ✅ |
| `im:resource` | 资源文件读写 | 需开通（下载文件需要） |
| `im:resource:download` | 下载消息资源 | ⭐ 关键权限 |

## 实现计划

### Phase 1：基础设施（本 PR）

1. **util/feishu.py** 新增：
   - `download_resource(message_id, file_key, output_path, token)` — 同步下载文件
2. **message_manager.py** 改动：
   - `Message` 增加 `msg_type` 字段
   - `_extract_text` → 改名为 `_extract_content`，兼容 non-text 类型
   - `on_ws_message` 中对 non-text 消息的解析 + 下载 + 系统消息记录
3. **config.py** 新增：
   - `Config.file_storage_dir`
4. **config.json** 新增配置项

### Phase 2：SingleChatManager 消费

- SingleChatManager 在 `_build_context_prefix` 中可以看到文件路径
- OpenClaw 收到的提示词里包含 `[File: ...]` 信息
- 主 session 可直接读取文件

## 未解决问题（后续再处理）

- 发文件能力（不在本 PR 范围）
- 多媒体消息的富文本展示
- 文件类型白名单/安全过滤
- 存储空间管理（定期清理）

---

*设计版本: v1, 2026-05-21*
