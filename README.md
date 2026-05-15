# Public Session — 社会通道飞书消息装置

通过飞书 bot (james_pm) 与飞书用户进行消息收发、对话管理。

## 架构概览

常驻 Python 进程，1s 主循环轮询 + WS 长连接实时接收。OneTick 检测等待对话的 sender，
启动 SingleChatManager 阻塞处理。

```
┌─ 主循环（Python 进程，1s 间隔）───────────────────────┐
│                                                        │
│  while True:                                           │
│    if stop_file_exists():                              │
│      cleanup()                                         │
│      break                                             │
│                                                        │
│    OneTick(config, mgr, token_provider)                 │
│      │  pick_candidate() → 选最久等待 sender            │
│      │  SingleChatManager.run()  ← 阻塞处理            │
│      │    │ poll_new → debounce 2s → batch → reply     │
│      │    └─ 超时 30s 退出                              │
│                                                        │
│    sleep(1s)                                           │
│                                                        │
└────────────────────────────────────────────────────────┘

         ┌─ WS 线程（后台 daemon）─────────────┐
         │  lark-oapi 长连接                     │
         │  收到消息 → 加锁写入 MessageTable    │
         │  NameResolver 懒缓存 open_id→name    │
         │  mark_get_on_receive 打 Get 表示在线  │
         └──────────────────────────────────────┘
```

## 目录结构

```
/james_pm/public_session/
├── public_session.py               # 主入口，主循环 + OneTick
├── message_manager.py              # Message, MessageTable, MessageManager
├── scheduler.py                    # pick_candidate 最久等待调度
├── single_chat_manager/            # 单次完整会话管理
│   ├── __init__.py
│   └── single_chat_manager.py      # SingleChatManager: run() 阻塞执行
├── config.json                     # 实例配置
├── requirements.txt                # Python 依赖
├── run.sh                          # 启动脚本
├── stop.sh                         # 停止脚本（写 stop 文件）
├── test_message_manager.py         # MessageManager 集成测试
├── README.md                       # 本文件
├── legacy/                         # 旧版代码归档
├── state/                          # 运行时状态（last_processed.json, log）
└── util/
    ├── __init__.py
    ├── config.py                   # JSON 配置加载
    └── feishu.py                   # 飞书 REST API 通用封装
```

## 快速启动

```bash
# 1. 安装依赖
cd /james_pm/public_session
pip install -r requirements.txt

# 2. 设置飞书 bot 身份（环境变量）
export PUBLIC_FEISHU_APP_ID="cli_xxx"
export PUBLIC_FEISHU_APP_SECRET="xxx"

# 3. 启动（后台运行）
bash run.sh &

# 4. 停止
bash stop.sh
```

## MessageManager 测试

```bash
# 启动集成测试（给 james_pm bot 发一条消息验证 WS 收发）
cd /james_pm/public_session
python3 test_message_manager.py
```

## 上下班控制

| 命令 | 行为 |
|------|------|
| `bash run.sh` | 启动主循环进程（前台运行，加 `&` 后台化） |
| `bash stop.sh` | 写入 stop 文件 → 进程自动退出并清理 stop 文件 |

## 配置文件

```json
{
  "state_dir": "/james_pm/public_session/state",
  "log_file": "/james_pm/public_session/state/messages.log",
  "stop_file": "/james_pm/public_session/state/.public_session.stop"
}
```

## Session Flow

### OneTick
1. 用 `scheduler.pick_candidate()` 从 MessageManager snapshot 中选最久等待的 sender
2. 若无候选，直接返回
3. 有候选 → 创建 SingleChatManager → 调用 `run()` 阻塞执行

### SingleChatManager.run()
1. 从 `last_processed.json` 读此 sender 的处理断点
2. 进入等待循环：
   - `_poll_new_messages()`：从 snapshot 取所有新消息
   - 2 秒 **debounce**：等用户连续发完再处理
   - `_process_batch()`：一批消息 → 一条"看到了"回复 → 标记 Done
3. 30 秒无消息 → 超时退出

### 消息处理逻辑
```
用户消息 → MessageManager WS 收集 → OneTick 发现 → SCM.run()
  → poll_new_messages（debounce 2s）
  → process_batch（回复"看到了"、标记 Done、更新 last_processed）
  → 继续 poll
  → 30s 超时 → 退出
```

### last_processed.json
```
{sender_open_id: last_processed_msg_id}
```
- OneTick 只读，SingleChatManager 读写
- 作为进程重启的持久化断点

## 设计原则

- **OneTick = 唯一入口**：所有业务逻辑在 OneTick 内，外部不关心内部状态
- **SingleChatManager = 一次会话**：run() 阻塞执行，返回 ChatResult，实例用完即弃
- **MessageManager 只收不处理**：WS 线程只管收集消息，业务逻辑由 SCM 承担
- **快照隔离**：WS 线程与主循环通过 snapshot() 深拷贝解耦
- **Debounce**：连续消息合并处理，避免回复轰炸
- **stop 文件退出**：写 stop 文件 → 主循环检测 → cleanup → 自动删除 stop 文件
- **幂等**：`last_processed.json` 持久化，保证重复启动不重复处理

## 依赖

- Python 3.8+
- `lark-oapi>=1.6.0`（飞书 Python SDK，WS 长连接）
