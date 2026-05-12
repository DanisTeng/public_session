# Public Session — 社会通道飞书消息装置

通过飞书 bot (james_pm) 与飞书用户进行消息收发、对话管理。

## 架构概览

常驻 Python 进程，自带 0.5s 高精度主循环。OneTick 为唯一执行接口。

```
┌─ 主循环（Python 进程，0.5s 间隔）──────────┐
│                                              │
│  while True:                                 │
│    if stop_file_exists():                    │
│      cleanup()                               │
│      break                                   │
│                                              │
│    if trigger_flag or time >= next_tick_time:│
│      trigger_flag = False                    │
│      OneTick()             ← 唯一入口         │
│      schedule_next()       ← 自适应调度       │
│                                              │
│    sleep(0.5s)                               │
│                                              │
└──────────────────────────────────────────────┘

# WS 回调（并发线程）
收到新消息 → trigger_flag = True
```

### 核心设计原则

| 原则 | 说明 |
|------|------|
| **OneTick 统一入口** | 空闲态/占用态都在 OneTick 内判断，外部不关心内部状态 |
| **原子执行** | OneTick 一旦开始不被打断，Python 单线程自然保证 |
| **自适应间隔** | 固定 5 分钟间隔，执行长了少等，执行短了多等（公式：wait = max(0, 300 - elapsed)）|
| **立即触发标志** | WS 事件设置 flag，主循环 0.5s 内响应 |
| **stop 文件退出** | 写 stop 文件，主循环自动检测到后执行 cleanup 退出 |
| **Cleanup 一次性** | 退出循环时只执行一次 cleanup |

### 调度示例

- OneTick 耗时 4 分钟 → 1 分钟后触发下一轮（总间隔 5 分钟）
- OneTick 耗时 30 秒 → 4.5 分钟后触发
- WS 推送新消息 → flag 立即生效 → 不等定时直接触发

## 目录结构

```
skills/public-session/
├── public_session.py      # 主入口，主循环 + OneTick 骨架
├── config.json            # 实例配置（用户/会话/路径）
├── run.sh                 # 启动脚本
├── README.md              # 本文件
├── SKILL.md               # 技能文档（开放性工具说明）
├── util/
│   ├── __init__.py
│   ├── config.py          # JSON 配置加载工具
│   └── feishu.py          # 飞书 API 通用封装
├── scripts/
│   └── public_session.sh  # shell 工具集
```

## 快速启动

```bash
# 设置飞书 bot 身份（环境变量）
export PUBLIC_FEISHU_APP_ID="cli_xxx"
export PUBLIC_FEISHU_APP_SECRET="xxx"

# 启动
cd skills/public-session
python3 public_session.py config.json
```

## 上下班控制

| 命令 | 行为 |
|------|------|
| `public session run` | 清理旧 stop 文件 → 启动 Python 主循环进程 |
| `public session stop` | 写入 stop 文件 → 等待进程自动退出 |

## 配置文件

```json
{
  "env_app_id": "PUBLIC_FEISHU_APP_ID",
  "env_app_secret": "PUBLIC_FEISHU_APP_SECRET",
  "target_user_open_id": "ou_xxx",
  "chat_id": "oc_xxx",
  "state_dir": "~/.openclaw/workspace/memory/public-session",
  "log_file": "~/.openclaw/workspace/memory/public-session/messages.log",
  "stop_file": "~/.openclaw/workspace/.public_session.stop"
}
```

## 设计原则

- **OneTick = 唯一入口**：所有业务逻辑（空闲态/占用态）都在 OneTick 内
- **主循环保障**：0.5s 轮询 + 自适应定时 + 标志位，不依赖操作系统定时器精度
- **WS 门铃模式**：WS 回调只设 trigger_flag，不阻塞、不处理消息
- **幂等**：已处理消息 ID 持久化，保证重复执行不重复处理
- **Cleanup 一次性**：整个进程退出时才做，不是每 tick

## 依赖

- Python 3.8+
- `lark-oapi`（飞书 SDK，WS 长连接需要）
