# Public Session — 社会通道飞书消息装置

通过飞书 bot (james_pm) 与飞书用户进行消息收发、对话管理。

## 架构概览

常驻 server 结构，自带内部时钟 + WS 长连接事件驱动。双态运行。

```
┌──────────────────────────────────────┐
│          public_session.py           │
│                                      │
│  ┌──────────────────────────────┐   │
│  │      WS 长连接（lark-oapi）    │   │
│  │  └→ 收到推送 → 写 event.flag │   │
│  └──────────────────────────────┘   │
│                                      │
│  ┌──────────────────────────────┐   │
│  │      内部定时器（兜底 tick）   │   │
│  └──────────────────────────────┘   │
│                                      │
│  ┌──────────────────────────────┐   │
│  │        双态状态机             │   │
│  │  ┌─────────────────────┐    │   │
│  │  │ 空闲态 OneIdleTick  │    │   │
│  │  │ 拉消息→已读→判断    │    │   │
│  │  └─────────────────────┘    │   │
│  │  ┌─────────────────────┐    │   │
│  │  │ 占用态 OneBusyTick  │    │   │
│  │  │ 对话管理+sessions   │    │   │
│  │  └─────────────────────┘    │   │
│  └──────────────────────────────┘   │
└──────────────────────────────────────┘
```

### 双态说明

| 状态 | 触发 | 做的事情 |
|------|------|---------|
| **空闲态** | WS 推送 / 定时到期 | 拉最近消息 → Get 已读 → 判断是否进入占用态 |
| **占用态** | OneIdleTick 决策进入 | 与某用户持续对话，走 persistent session |

### 退出占用态的条件
1. AI 自主判断（回复含 [SESSION_END]）
2. 回合数超过硬限制（如 15 轮）
3. 用户沉默超时（如 5 分钟无回复）

## 目录结构

```
skills/public-session/
├── public_session.py      # 主入口，状态机 + 业务逻辑
├── config.json            # 实例配置（用户/会话/路径）
├── run.sh                 # 启动脚本
├── README.md              # 本文件
├── SKILL.md               # 技能文档（开放性工具说明）
├── util/
│   ├── __init__.py
│   ├── config.py          # JSON 配置加载工具
│   └── feishu.py          # 飞书 API 通用封装
└── scripts/
    ├── public_session.sh  # 旧版 shell 工具集
    └── send_msg.sh        # 旧版兼容
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

## 配置文件

```json
{
  "env_app_id": "PUBLIC_FEISHU_APP_ID",
  "env_app_secret": "PUBLIC_FEISHU_APP_SECRET",
  "target_user_open_id": "ou_xxx",
  "chat_id": "oc_xxx",
  "state_dir": "~/.openclaw/workspace/memory/public-session",
  "log_file": "~/.openclaw/workspace/memory/public-session/messages.log"
}
```

`config.json` 是实例级配置，换用户/换 bot 时只改此文件，不动代码。

飞书 APP_ID/APP_SECRET 走环境变量，不写进文件。

## 设计原则

- **WS 门铃模式**：长连接只负责"有新消息"的信号，不处理消息内容
- **空闲态人畜无害**：OneIdleTick 只做拉取+已读，不涉及 AI 调用
- **占用态不依赖 agent turn**：使用 persistent session + sessions_send 同步等回复，外部控制对话节奏
- **安全监控**：sessions_send 超时、回合数硬限制、沉默超时，全部在占用态管理器内
- **幂等**：已处理消息 ID 持久化，保证重复运行不重复处理

## 依赖

- Python 3.8+
- `lark-oapi`（飞书 SDK，WS 长连接需要）
- OpenClaw Gateway（用于 sessions_send）
