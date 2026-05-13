# Public Session — 社会通道飞书消息装置

通过飞书 bot (james_pm) 与飞书用户进行消息收发、对话管理。

## 架构概览

常驻 Python 进程，0.5s 主循环轮询 + WS 长连接实时接收。OneTick 为唯一业务入口。

```
┌─ 主循环（Python 进程，0.5s 间隔）────────────────────┐
│                                                        │
│  while True:                                           │
│    if stop_file_exists():                              │
│      cleanup()                                         │
│      break                                             │
│                                                        │
│    if trigger_flag or time >= next_tick_time:          │
│      trigger_flag = False                              │
│      snapshot = message_manager.snapshot()  ← 冻结快照  │
│      OneTick(snapshot)               ← 唯一业务入口    │
│      schedule_next()                 ← 自适应调度      │
│                                                        │
│    sleep(0.5s)                                         │
│                                                        │
└────────────────────────────────────────────────────────┘

         ┌─ WS 线程（后台 daemon）─────────────┐
         │  lark-oapi 长连接                     │
         │  收到消息 → 加锁写入 MessageHistoryTable │
         └──────────────────────────────────────┘
```

### MessageManager

WS 线程与主循环通过 **MessageManager.snapshot()** 交互：

```
WS 线程：收到消息 → 加锁 → 写入 MessageHistoryTable → 解锁
OneTick：mgr.snapshot() → 加锁 → 深拷贝整个 table → 解锁 → 拿到冻结快照
```

## 目录结构

```
/james_pm/public_session/
├── public_session.py       # 主入口，主循环 + OneTick
├── message_manager.py      # Message, MessageHistoryTable, MessageManager
├── config.json             # 实例配置
├── requirements.txt        # Python 依赖
├── run.sh                  # 启动脚本
├── stop.sh                 # 停止脚本（写 stop 文件）
├── test_message_manager.py # MessageManager 集成测试
├── README.md               # 本文件
├── util/
│   ├── __init__.py
│   ├── config.py           # JSON 配置加载
│   └── feishu.py           # 飞书 REST API 通用封装
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
  "env_app_id": "PUBLIC_FEISHU_APP_ID",
  "env_app_secret": "PUBLIC_FEISHU_APP_SECRET",
  "target_user_open_id": "ou_xxx",
  "chat_id": "oc_xxx",
  "chat_ids": ["oc_xxx"],
  "state_dir": "/james_pm/public_session/state",
  "log_file": "/james_pm/public_session/state/messages.log",
  "stop_file": "/james_pm/public_session/state/.public_session.stop"
}
```

## 设计原则

- **OneTick = 唯一入口**：所有业务逻辑在 OneTick 内，外部不关心内部状态
- **主循环保障**：0.5s 轮询 + 自适应定时 + 标志位，不依赖操作系统定时器精度
- **快照隔离**：WS 线程与主循环通过快照解耦，无需共享状态
- **stop 文件退出**：写 stop 文件 → 主循环检测 → cleanup → 自动删除 stop 文件
- **幂等**：已处理消息 ID 持久化，保证重复执行不重复处理
- **Cleanup 一次性**：整个进程退出时才做，不是每 tick

## 依赖

- Python 3.8+
- `lark-oapi>=1.6.0`（飞书 Python SDK，WS 长连接）
