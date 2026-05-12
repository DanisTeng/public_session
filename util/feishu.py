"""飞书开放平台 API 封装

提供通用飞书 API 调用能力，不含任何业务逻辑。
调用者需自己管理 token 生命周期。
"""

import json
import urllib.request
import urllib.error

API_BASE = "https://open.feishu.cn/open-apis"


def _request(path, token, method="GET", body=None):
    """发送飞书 API 请求

    所有飞书 API 调用的底层函数。

    Pre-condition: token 不能为空（获取 token 本身不走此函数）

    Args:
        path: API 路径（如 /im/v1/messages）
        token: tenant_access_token
        method: HTTP 方法，默认 GET
        body: 请求体 dict，会自动序列化

    Returns:
        dict: 飞书 API 响应（已解析 JSON）。出错时返回 {"code": -1, "msg": ...}
    """
    assert token, "_request requires a valid token"

    url = f"{API_BASE}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    data = json.dumps(body).encode("utf-8") if body else None

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"code": -1, "msg": f"HTTP {e.code}: {e.read().decode()[:200]}"}
    except Exception as e:
        return {"code": -1, "msg": str(e)}


def get_token(app_id, app_secret):
    """获取 tenant_access_token

    飞书 bot 的身份凭证，用于后续 API 调用。

    Args:
        app_id: 飞书自建应用的 App ID
        app_secret: 飞书自建应用的 App Secret

    Returns:
        str: tenant_access_token，失败返回 None
    """
    body = {"app_id": app_id, "app_secret": app_secret}
    req = urllib.request.Request(
        f"{API_BASE}/auth/v3/tenant_access_token/internal",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    if result.get("code") != 0:
        return None
    return result["tenant_access_token"]


def list_messages(chat_id, token, page_size=20):
    """拉取会话消息（按创建时间倒序）"""
    return _request(
        f"/im/v1/messages?container_id_type=chat&container_id={chat_id}"
        f"&page_size={page_size}&sort_type=ByCreateTimeDesc",
        token=token,
    )


def reply_message(msg_id, token, text):
    """回复消息"""
    content = json.dumps({"text": text})
    return _request(
        f"/im/v1/messages/{msg_id}/reply",
        token=token,
        method="POST",
        body={"content": content, "msg_type": "text"},
    )


def send_text_message(open_id, token, text):
    """发送文本消息给指定用户"""
    content = json.dumps({"text": text})
    return _request(
        "/im/v1/messages?receive_id_type=open_id",
        token=token,
        method="POST",
        body={
            "receive_id": open_id,
            "msg_type": "text",
            "content": content,
        },
    )


def react_message(msg_id, token, emoji="Get"):
    """给消息添加表情"""
    return _request(
        f"/im/v1/messages/{msg_id}/reactions",
        token=token,
        method="POST",
        body={"reaction_type": {"emoji_type": emoji}},
    )


def get_reactions(msg_id, token, page_size=20):
    """读取消息上的所有表情回复"""
    return _request(
        f"/im/v1/messages/{msg_id}/reactions?page_size={page_size}",
        token=token,
    )
