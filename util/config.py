"""配置加载工具

从 JSON 文件加载应用配置。
配置内容是纯业务数据，不包含飞书 APP_SECRET 等敏感信息。
"""

import json
import os
import sys


def load(path):
    """从 JSON 文件加载配置

    Pre-condition: path 指向一个可读的 JSON 文件

    Args:
        path: 配置文件路径

    Returns:
        dict: 解析后的配置对象

    退出码：
        1 — 文件不存在
        2 — JSON 格式错误
    """
    if not os.path.exists(path):
        print(f"ERROR: config file not found: {path}", file=sys.stderr, flush=True)
        sys.exit(1)

    with open(path) as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            print(f"ERROR: invalid JSON in {path}: {e}", file=sys.stderr, flush=True)
            sys.exit(2)
