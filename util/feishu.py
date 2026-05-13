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


def list_chats(token, page_size=50):
    """列出 bot 加入的所有群聊/会话

    Pre-condition: token 有效

    Args:
        token: tenant_access_token
        page_size: 每页数量（最大 100）

    Returns:
        list[dict]: 会话列表，每个元素包含 chat_id, name 等字段
    """
    assert token, "list_chats requires a valid token"
    items = []
    page_token = ""
    while True:
        params = f"page_size={page_size}"
        if page_token:
            params += f"&page_token={page_token}"
        result = _request(f"/im/v1/chats?{params}", token=token)
        if result.get("code") != 0:
            return result
        data = result.get("data", {})
        items.extend(data.get("items", []))
        if not data.get("has_more"):
            break
        page_token = data.get("page_token", "")
    return {"code": 0, "data": {"items": items}}


def list_chat_messages(chat_id, token, page_size=50):
    """拉取会话消息列表（按创建时间倒序）

    封装 list_messages，明确指定 chat_id 类型为 chat。

    Args:
        chat_id: 会话 ID (oc_xxx)
        token: tenant_access_token
        page_size: 每页数量

    Returns:
        dict: 飞书 API 原始响应
    """
    return list_messages(chat_id, token, page_size=page_size)


def poll_new_messages(chat_ids, token, processed_ids, page_size=50):
    """轮询新消息：从多个会话拉取消息，过滤出未处理的新消息

    Pre-condition:
        - token 有效
        - processed_ids 是 set[str]

    Args:
        chat_ids: list[str]，要轮询的会话 ID 列表
        token: tenant_access_token
        processed_ids: set[str]，已处理过的消息 ID 集合
        page_size: 每个会话拉取的消息数量

    Returns:
        list[dict]: 新消息列表，按创建时间升序排列。每条消息包含:
            - message_id
            - chat_id
            - sender_id
            - text (纯文本内容)
            - create_time
            等字段。返回空列表表示没有新消息。
    """
    new_messages = []
    for cid in chat_ids:
        result = list_chat_messages(cid, token, page_size=page_size)
        if result.get("code") != 0:
            continue
        items = result.get("data", {}).get("items", [])
        for msg in items:
            msg_id = msg.get("message_id", "")
            if msg_id in processed_ids:
                continue
            # 只处理用户发的消息，不处理自己 bot 发的
            sender_type = msg.get("sender", {}).get("sender_type", "")
            if sender_type == "app":
                processed_ids.add(msg_id)  # 也标记已处理，避免无限循环
                continue
            new_messages.append(msg)
    # 按创建时间升序排列
    new_messages.sort(key=lambda m: m.get("create_time", "0"))
    return new_messages
