"""
agent.py — OpenClaw agent 子 session 调用封装

通过 subprocess 执行 `openclaw agent` 命令，与 PM 子 agent 进行同步通信。
提供三个核心接口：
  1. start_session()  — 初始化或确认 session 可用
  2. call_agent()     — 发送消息并阻塞等待回复
  3. close_session()  — 主动结束 session

设计说明：
  - 使用 `openclaw agent --agent pm --session-id <id> --json` 模式
  - 阻塞同步调用，适合 Python WS 监听器"收消息 → 调 agent → 回复"的场景
  - session_id 可在多个调用间复用，保持对话连续性
  - 不支持并行（PM 单线程串行设计，无并发问题）

Pre-condition:
  - `openclaw` 命令在 PATH 中
  - 目标 agent（如 `pm`）已通过 `openclaw agents add` 创建
  - `--agent <name>` 指定的 agent 有对应的 agent workspace 和模型配置
"""

import json
import os
import subprocess
import sys

# ── 常量 ────────────────────────────────────────────────────────────────

DEFAULT_AGENT = "pm-agent"
"""默认 agent ID，需提前通过 `openclaw agents add` 创建"""

DEFAULT_SESSION_ID = "public-session-pm"
"""默认 session ID，跨多次调用保持对话上下文"""

DEFAULT_TIMEOUT = 240
"""单次 agent 调用的超时秒数（默认 4 分钟）"""

# ── 核心函数 ────────────────────────────────────────────────────────────


def start_session(agent=DEFAULT_AGENT, session_id=DEFAULT_SESSION_ID):
    """确保子 agent session 可用

    向目标 agent 发送一条初始化消息，创建或确认 session 已就绪。
    返回 True 表示 session 可用。

    Args:
        agent: agent ID（需已通过 openclaw agents add 创建）
        session_id: session ID，保持对话连续性

    Returns:
        bool: session 是否成功启动
    """
    cmd = [
        "openclaw", "agent",
        "--agent", agent,
        "--session-id", session_id,
        "--message", "SYSTEM_INIT: session ready",
        "--json",
        "--timeout", "30",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=35,
        )
        stdout = result.stdout
    except subprocess.TimeoutExpired:
        return False
    except FileNotFoundError:
        return False

    data = json.loads(stdout)
    return data.get("status") == "ok"


def call_agent(chat_history, agent=DEFAULT_AGENT,
               session_id=DEFAULT_SESSION_ID, timeout=DEFAULT_TIMEOUT):
    """发送聊天记录给子 agent，阻塞等待回复

    将飞书聊天记录（消息列表）送入 OpenClaw agent 引擎，
    让 agent 扮演 PM 角色执行任务，输出回复文本。

    Pre-condition:
        start_session() 已成功调用过，或 session 已有上下文

    Args:
        chat_history: 一段或多段聊天记录文本
        agent: agent ID
        session_id: session ID
        timeout: 超时秒数，默认 240

    Returns:
        dict: {
            "success": bool,
            "reply": str | None,        # agent 回复文本，成功时有
            "error": str | None,        # 错误描述，失败时有
            "duration_ms": int | None,  # agent 处理耗时
            "usage": dict | None,       # token 用量
        }
    """
    cmd = [
        "openclaw", "agent",
        "--agent", agent,
        "--session-id", session_id,
        "--message", chat_history,
        "--json",
        "--timeout", str(timeout),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 10,
        )
        stdout = result.stdout
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "reply": None,
            "error": f"subprocess timeout after {timeout + 10}s",
            "duration_ms": None,
            "usage": None,
        }
    except FileNotFoundError:
        return {
            "success": False,
            "reply": None,
            "error": "openclaw command not found in PATH",
            "duration_ms": None,
            "usage": None,
        }

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as e:
        return {
            "success": False,
            "reply": None,
            "error": f"JSON parse error: {e}",
            "duration_ms": None,
            "usage": None,
        }

    status = data.get("status")
    if status != "ok":
        return {
            "success": False,
            "reply": None,
            "error": f"agent returned status={status}",
            "duration_ms": None,
            "usage": None,
        }

    # 提取回复文本
    payloads = data.get("result", {}).get("payloads", [])
    meta = data.get("result", {}).get("meta", {})

    reply_text = None
    if payloads:
        # payloads[0] 是 agent 回复的主要文本
        reply_text = payloads[0].get("text")

    return {
        "success": True,
        "reply": reply_text,
        "error": None,
        "duration_ms": meta.get("durationMs"),
        "usage": meta.get("agentMeta", {}).get("usage"),
    }


def close_session(agent=DEFAULT_AGENT, session_id=DEFAULT_SESSION_ID):
    """主动结束子 agent session

    发送终止消息给 session，释放资源。
    如果没有活跃 session，静默成功。

    Args:
        agent: agent ID
        session_id: session ID

    Returns:
        bool: 是否成功关闭
    """
    cmd = [
        "openclaw", "agent",
        "--agent", agent,
        "--session-id", session_id,
        "--message", "SYSTEM_SHUTDOWN: session closed",
        "--json",
        "--timeout", "15",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=20,
        )
        _ = result.stdout
        return True
    except Exception:
        return False


# ── CLI 入口（测试用） ────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Call OpenClaw PM agent subprocess")
    parser.add_argument("action", choices=["start", "call", "close", "test"],
                        help="Action to perform")
    parser.add_argument("--message", "-m", default="Hello",
                        help="Message text (for 'call' action)")
    parser.add_argument("--agent", default=DEFAULT_AGENT,
                        help=f"Agent ID (default: {DEFAULT_AGENT})")
    parser.add_argument("--session-id", default=DEFAULT_SESSION_ID,
                        help=f"Session ID (default: {DEFAULT_SESSION_ID})")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"Timeout in seconds (default: {DEFAULT_TIMEOUT})")

    args = parser.parse_args()

    if args.action == "start":
        ok = start_session(agent=args.agent, session_id=args.session_id)
        print(json.dumps({"success": ok}, indent=2))

    elif args.action == "call":
        result = call_agent(
            args.message,
            agent=args.agent,
            session_id=args.session_id,
            timeout=args.timeout,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.action == "close":
        ok = close_session(agent=args.agent, session_id=args.session_id)
        print(json.dumps({"success": ok}, indent=2))

    elif args.action == "test":
        # 全流程测试：start → call → call → close
        print("=== TEST: start session ===")
        ok = start_session(agent=args.agent, session_id=args.session_id)
        print(f"start_session: {'✅' if ok else '❌'}")

        if ok:
            print("\n=== TEST: call agent (first) ===")
            r1 = call_agent("Hello", agent=args.agent,
                           session_id=args.session_id, timeout=args.timeout)
            print(f"success: {r1['success']}")
            if r1.get("reply"):
                print(f"reply: {r1['reply'][:100]}")
            if r1.get("duration_ms"):
                print(f"duration: {r1['duration_ms']}ms")

            print("\n=== TEST: call agent (second, different context) ===")
            r2 = call_agent("Hi again, this is a follow-up.",
                           agent=args.agent,
                           session_id=args.session_id,
                           timeout=args.timeout)
            print(f"success: {r2['success']}")
            if r2.get("reply"):
                print(f"reply: {r2['reply'][:100]}")
            if r2.get("duration_ms"):
                print(f"duration: {r2['duration_ms']}ms")

        print("\n=== TEST: close session ===")
        ok = close_session(agent=args.agent, session_id=args.session_id)
        print(f"close_session: {'✅' if ok else '❌'}")
