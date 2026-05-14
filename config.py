"""配置管理

从 JSON 文件加载应用配置，提供 Config 数据类封装。
配置内容是纯业务数据，不包含飞书 APP_SECRET 等敏感信息。
"""

import json
import sys
from dataclasses import dataclass


@dataclass
class Config:
    """public_session 配置

    Attributes:
        env_app_id: 环境变量名，对应飞书 App ID
        env_app_secret: 环境变量名，对应飞书 App Secret
        state_dir: 状态文件目录
        log_file: 日志文件路径（可选），不设则不写文件
        stop_file: stop 文件路径
    """
    env_app_id: str
    env_app_secret: str
    state_dir: str = ""
    log_file: str = ""
    stop_file: str = ""


def load(path) -> Config:
    """从 JSON 文件加载配置

    Pre-condition: path 指向一个可读的 JSON 文件

    Args:
        path: 配置文件路径

    Returns:
        Config: 配置实例

    退出码：
        1 — 文件不存在
        2 — JSON 格式错误
    """
    if not os.path.exists(path):
        print(f"ERROR: config file not found: {path}", file=sys.stderr, flush=True)
        sys.exit(1)

    with open(path) as f:
        try:
            raw = json.load(f)
        except json.JSONDecodeError as e:
            print(f"ERROR: invalid JSON in {path}: {e}", file=sys.stderr, flush=True)
            sys.exit(2)

    return Config(**raw)
