#!/usr/bin/env python3
"""
test_temp_session.py — Integration test for run_temp_session.

Tests:
  - Basic truth check: 1000 > 100 → agent should return true/false
  - Failure handling: empty task → None

Usage:
  python3 test_temp_session.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from util.openclaw import run_temp_session


def test_basic_boolean():
    """Agent 应该能判断 1000 > 100，返回类似 True / true / yes 的内容"""
    result = run_temp_session(
        "判断数字大小：1000 是否大于 100？只回复 True 或 False，不要其他内容。"
    )
    assert result is not None, f"Expected some output, got None"
    text = result.strip().lower()
    assert "true" in text or "yes" in text, (
        f"Expected agent to say True/yes for '1000 > 100', "
        f"got: {result!r}"
    )
    print(f"✅ test_basic_boolean passed: {result!r}")


def test_empty_task():
    """空任务应返回 None"""
    result = run_temp_session("")
    assert result is None, f"Expected None for empty task, got {result!r}"
    print(f"✅ test_empty_task passed")


def test_timeout_short():
    """极短超时下应返回 None（任务来不及完成）"""
    result = run_temp_session("请写一篇 500 字的中文散文", timeout=1)
    assert result is None, f"Expected timeout -> None, got {result!r}"
    print(f"✅ test_timeout_short passed")


if __name__ == "__main__":
    print("=== test_temp_session.py ===")
    test_basic_boolean()
    test_empty_task()
    test_timeout_short()
    print("\n🎉 All tests passed!")
