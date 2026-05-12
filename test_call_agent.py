#!/usr/bin/env python3
"""
test_call_agent.py — 验证 util/agent.py 的子 session 调用能力

测试流程：
  1. start_session()    → 确认 session 可用
  2. call_agent("Hi")   → 第一次呼叫，获取回复
  3. call_agent("...")  → 第二次呼叫（带不同上下文，验证上下文连续性）
  4. close_session()    → 清理

用法：
  python3 test_call_agent.py

依赖：
  - openclaw CLI 在 PATH 中
  - pm-agent 已通过 `openclaw agents add` 创建
"""

import json
import sys
import os

# 确保能找到 util 包
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "util"))

import agent

PASS = 0
FAIL = 0


def check(desc, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {desc}")
    else:
        FAIL += 1
        marker = "  ❌"
        if detail:
            marker += f"  ({detail})"
        print(f"{marker} {desc}")


print("=" * 60)
print("🧪  test_call_agent — PM Agent Session Test")
print("=" * 60)

# ── 1. Start ──
print(f"\n{'─'*60}")
print("📌  Step 1: start_session()")
print(f"{'─'*60}")
ok = agent.start_session()
check(f"start_session() returns True", ok, f"got {ok}")

if not ok:
    print("\n⚠️  start_session failed — check if pm-agent exists and openclaw is in PATH")
    sys.exit(1)

# ── 2. First call ──
print(f"\n{'─'*60}")
print("📌  Step 2: call_agent(\"Hello, who are you?\")")
print(f"{'─'*60}")
r1 = agent.call_agent("Hello, who are you?")
check(f"call_agent returns success=True", r1["success"], f"got success={r1['success']}")

if r1["success"]:
    check(f"reply is not empty", bool(r1["reply"]))
    if r1["reply"]:
        print(f"\n     Reply snippet: {r1['reply'][:120]}")
    if r1["duration_ms"]:
        print(f"     Duration: {r1['duration_ms']}ms ({r1['duration_ms']/1000:.1f}s)")
    if r1["usage"]:
        usage = r1["usage"]
        total = usage.get("total", 0)
        print(f"     Token usage: input={usage.get('input', 0)} output={usage.get('output', 0)} total={total}")
else:
    print(f"     Error: {r1.get('error')}")
    # 即使第一个失败了也继续试第二个

# ── 3. Second call (context continuity) ──
print(f"\n{'─'*60}")
print("📌  Step 3: call_agent(\"What did I ask you just now?\")")
print("       (This tests session context continuity)")
print(f"{'─'*60}")
r2 = agent.call_agent("What did I ask you just now?")
check(f"call_agent returns success=True", r2["success"], f"got success={r2['success']}")

if r2["success"]:
    check(f"reply is not empty", bool(r2["reply"]))
    if r2["reply"]:
        print(f"\n     Reply snippet: {r2['reply'][:120]}")
    if r2["duration_ms"]:
        print(f"     Duration: {r2['duration_ms']}ms ({r2['duration_ms']/1000:.1f}s)")

# ── 4. Close ──
print(f"\n{'─'*60}")
print("📌  Step 4: close_session()")
print(f"{'─'*60}")
ok = agent.close_session()
check(f"close_session() returns True", ok, f"got {ok}")

# ── Summary ──
print(f"\n{'='*60}")
total = PASS + FAIL
print(f"📊  Results: {PASS}/{total} passed, {FAIL}/{total} failed")
if FAIL == 0:
    print("🎉  All tests passed!")
else:
    print(f"❌  {FAIL} test(s) failed")
print(f"{'='*60}")
