"""配置管理

从 JSON 文件加载应用配置，提供 Config 数据类封装。
配置内容是纯业务数据，不包含飞书 APP_SECRET 等敏感信息。
"""

import json
import os
import sys
import time
from dataclasses import dataclass

from util.feishu import get_token as _feishu_get_token


# ── 缓存 Token ─────────────────────────────────────────────────────────

class CachedTokenProvider:
    """带缓存的 tenant_access_token 获取器

    缓存 90 分钟（飞书 token 有效期 2 小时），避免每秒请求新 token。

    用法：
        provider = CachedTokenProvider(app_id, app_secret)
        token = provider.get()  # 自动缓存/刷新
    """

    _CACHE_TTL = 5400  # 90 分钟，留 30 分钟余量

    def __init__(self, app_id: str, app_secret: str):
        self._app_id = app_id
        self._app_secret = app_secret
        self._token: str | None = None
        self._expires_at: float = 0.0

    def get(self) -> str | None:
        if time.time() < self._expires_at and self._token is not None:
            return self._token
        self._token = _feishu_get_token(self._app_id, self._app_secret)
        if self._token:
            self._expires_at = time.time() + self._CACHE_TTL
        return self._token

    def invalidate(self):
        self._token = None
        self._expires_at = 0.0


# ── 配置 ────────────────────────────────────────────────────────────────

@dataclass
class Config:
    """public_session 配置

    Attributes:
        app_id: 飞书 App ID
        app_secret: 飞书 App Secret
        state_dir: 状态文件目录
        log_file: 日志文件路径（可选），不设则不写文件
        stop_file: stop 文件路径
        file_storage_dir: 文件存储目录（可选），不设则默认 state_dir/../received_files/
    """
    app_id: str = ""
    app_secret: str = ""
    state_dir: str = ""
    log_file: str = ""
    stop_file: str = ""
    file_storage_dir: str = ""

    @property
    def resolved_app_id(self) -> str:
        if self.app_id:
            return self.app_id
        return os.environ.get("PUBLIC_FEISHU_APP_ID", "")

    @property
    def resolved_app_secret(self) -> str:
        if self.app_secret:
            return self.app_secret
        return os.environ.get("PUBLIC_FEISHU_APP_SECRET", "")

    def new_token_provider(self) -> CachedTokenProvider:
        return CachedTokenProvider(self.resolved_app_id, self.resolved_app_secret)


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

    raw = {k: v for k, v in raw.items() if k in Config.__dataclass_fields__}
    return Config(**raw)
