#!/usr/bin/env python3
"""
send_file.py — 通过飞书 bot 发送文件给指定用户

独立 main 入口，供 OpenClaw agent 在对话中调用。

用法：
    python -m util.send_file <open_id> <file_path>
    python -m util.send_file --list  # 列出支持的格式

环境变量（与 public_session 共用）：
    PUBLIC_FEISHU_APP_ID      — 飞书自建应用 App ID
    PUBLIC_FEISHU_APP_SECRET  — 飞书自建应用 App Secret

也可以在 config.json 中指定 app_id/app_secret（传 --config <path>）。

流程：
  1. 获取 tenant_access_token
  2. 上传文件到飞书，获取 file_key
  3. 发送文件消息给指定用户
"""

import json
import mimetypes
import os
import sys
import urllib.request
import urllib.error

API_BASE = "https://open.feishu.cn/open-apis"

# ── 支持的格式 ──────────────────────────────────────────────────────────

SUPPORTED_EXTENSIONS = {
    # 文档类
    ".txt", ".md", ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    ".ppt", ".pptx", ".csv", ".html", ".htm", ".xml", ".json",
    # 图片类（走 file 类型上传，不走 image 消息）
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg",
    # 音视频类
    ".mp3", ".wav", ".aac", ".flac", ".ogg",
    ".mp4", ".mov", ".avi", ".mkv", ".wmv", ".webm",
    # 压缩包
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    # 代码
    ".py", ".js", ".ts", ".java", ".cpp", ".c", ".h", ".hpp",
    ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".scala",
    ".sh", ".bat", ".ps1", ".yaml", ".yml", ".toml", ".ini",
    ".cfg", ".conf", ".sql", ".proto",
    # 其他常见格式
    ".log",
}


def get_token(app_id: str, app_secret: str) -> str | None:
    """获取 tenant_access_token"""
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
    except Exception as e:
        print(f"ERROR: 获取 token 失败: {e}", file=sys.stderr)
        return None
    if result.get("code") != 0:
        print(f"ERROR: 获取 token 失败: {result}", file=sys.stderr)
        return None
    return result["tenant_access_token"]


def _resolve_file_type(file_path: str) -> str:
    """根据文件扩展名获取飞书 file_type 参数。

    支持的 file_type：opus, mp4, pdf, doc, xls, ppt, stream
    非标准格式统一用 stream。
    """
    ext = os.path.splitext(file_path)[1].lower()
    type_map = {
        ".pdf": "pdf",
        ".doc": "doc", ".docx": "doc",
        ".xls": "xls", ".xlsx": "xls",
        ".ppt": "ppt", ".pptx": "ppt",
        ".mp4": "mp4",
        ".opus": "opus",
    }
    return type_map.get(ext, "stream")


def _build_multipart_body(file_path: str) -> tuple[bytes, str]:
    """构造 multipart/form-data 的 body 和 content-type。

    飞书 API 要求四个字段：
      - file_type: 文件类型（如 mp4, pdf, stream）
      - file_name: 文件名
      - file: 文件二进制

    Returns:
        (body_bytes, content_type_header)
    """
    file_name = os.path.basename(file_path)
    file_type = _resolve_file_type(file_path)
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"

    with open(file_path, "rb") as f:
        file_data = f.read()

    parts = [
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file_type"\r\n\r\n'
        f"{file_type}\r\n".encode("utf-8"),
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file_name"\r\n\r\n'
        f"{file_name}\r\n".encode("utf-8"),
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{file_name}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n".encode("utf-8"),
        file_data,
        f"\r\n".encode("utf-8"),
        f"--{boundary}--\r\n".encode("utf-8"),
    ]

    body = b"".join(parts)
    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type


def upload_file(token: str, file_path: str) -> dict:
    """上传文件到飞书，获取 file_key。

    Args:
        token: tenant_access_token
        file_path: 本地文件路径

    Returns:
        dict: {"code": 0, "file_key": "xxx"} 或 {"code": -1, "msg": "..."}
    """
    if not os.path.isfile(file_path):
        return {"code": -1, "msg": f"文件不存在: {file_path}"}

    file_name = os.path.basename(file_path)
    ext = os.path.splitext(file_name)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return {"code": -1, "msg": f"不支持的文件格式: {ext} (支持: {list(SUPPORTED_EXTENSIONS)[:10]}...)"}

    # 大小检查 (50MB)
    file_size = os.path.getsize(file_path)
    MAX_SIZE = 50 * 1024 * 1024
    if file_size > MAX_SIZE:
        return {
            "code": -1,
            "msg": f"文件过大 ({file_size / 1024 / 1024:.1f}MB > 50MB)",
        }

    body, content_type = _build_multipart_body(file_path)

    url = f"{API_BASE}/im/v1/files"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": content_type,
    }

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            detail = str(e)
        return {"code": -1, "msg": f"上传 HTTP {e.code}: {detail}"}
    except Exception as e:
        return {"code": -1, "msg": f"上传失败: {str(e)[:200]}"}

    if result.get("code") != 0:
        return {
            "code": result.get("code", -1),
            "msg": result.get("msg", f"上传失败: {result}"),
        }

    file_key = result.get("data", {}).get("file_key", "")
    if not file_key:
        return {"code": -1, "msg": "上传成功但未返回 file_key"}

    return {"code": 0, "file_key": file_key, "file_name": file_name}


def send_file_message(token: str, open_id: str, file_key: str) -> dict:
    """通过 file_key 发送文件消息给指定用户。

    Args:
        token: tenant_access_token
        open_id: 飞书用户的 open_id
        file_key: 上传后得到的 file_key

    Returns:
        dict: 飞书 API 响应
    """
    content = json.dumps({"file_key": file_key})
    url = f"{API_BASE}/im/v1/messages?receive_id_type=open_id"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    body = {
        "receive_id": open_id,
        "msg_type": "file",
        "content": content,
    }

    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers=headers, method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            detail = str(e)
        return {"code": -1, "msg": f"发送 HTTP {e.code}: {detail}"}
    except Exception as e:
        return {"code": -1, "msg": f"发送失败: {str(e)[:200]}"}


def load_config(config_path: str) -> dict:
    """从 JSON 文件加载配置。"""
    if not os.path.exists(config_path):
        return {}
    with open(config_path) as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def resolve_credentials(config_path: str) -> tuple[str, str]:
    """从 config.json 或环境变量解析 APP_ID/APP_SECRET。

    Returns:
        (app_id, app_secret) 或 (None, None)
    """
    cfg = load_config(config_path) if config_path else {}

    # 优先环境变量，其次 config.json
    app_id = (
        os.environ.get("PUBLIC_FEISHU_APP_ID")
        or cfg.get("env_app_id", "")
        or os.environ.get(cfg.get("env_app_id", ""), "")
    )
    app_secret = (
        os.environ.get("PUBLIC_FEISHU_APP_SECRET")
        or cfg.get("env_app_secret", "")
        or os.environ.get(cfg.get("env_app_secret", ""), "")
    )

    return app_id or "", app_secret or ""


# ── main ────────────────────────────────────────────────────────────────

def main():
    """CLI 入口

    用法：
        python -m util.send_file <open_id> <file_path>
        python -m util.send_file --list
        python -m util.send_file --help
    """
    # 检查可选参数：--config <path>
    config_path = ""
    args = sys.argv[1:]
    clean_args = []
    i = 0
    while i < len(args):
        if args[i] == "--config" and i + 1 < len(args):
            config_path = args[i + 1]
            i += 2
        elif args[i] == "--help":
            print(__doc__)
            sys.exit(0)
        elif args[i] == "--list":
            print("支持的格式:")
            for ext in sorted(SUPPORTED_EXTENSIONS):
                print(f"  {ext}")
            sys.exit(0)
        else:
            clean_args.append(args[i])
            i += 1

    if len(clean_args) < 2:
        print("用法: python -m util.send_file [--config <path>] <open_id> <file_path>", file=sys.stderr)
        print("       python -m util.send_file --list    # 列出支持的格式", file=sys.stderr)
        print("       python -m util.send_file --help    # 显示帮助", file=sys.stderr)
        sys.exit(1)

    open_id = clean_args[0]
    file_path = clean_args[1]

    # 解析凭证
    app_id, app_secret = resolve_credentials(config_path)
    if not app_id or not app_secret:
        print(
            "ERROR: 无法获取飞书凭证。请在环境变量中设置 "
            "PUBLIC_FEISHU_APP_ID 和 PUBLIC_FEISHU_APP_SECRET，"
            "或用 --config 指定 config.json。",
            file=sys.stderr,
        )
        sys.exit(1)

    # 1. 获取 token
    token = get_token(app_id, app_secret)
    if not token:
        print("ERROR: 无法获取飞书 API token", file=sys.stderr)
        sys.exit(1)

    # 2. 上传文件
    result = upload_file(token, file_path)
    if result.get("code") != 0:
        print(f"ERROR: 文件上传失败: {result.get('msg', '未知错误')}", file=sys.stderr)
        sys.exit(1)

    file_key = result["file_key"]
    file_name = result.get("file_name", os.path.basename(file_path))
    file_size = os.path.getsize(file_path)
    print(f"✅ 文件上传成功: {file_name} ({file_size / 1024:.1f}KB) → file_key={file_key}", file=sys.stderr)

    # 3. 发送文件消息
    send_result = send_file_message(token, open_id, file_key)
    if send_result.get("code") != 0:
        print(
            f"ERROR: 文件发送失败: {send_result.get('msg', '未知错误')}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"✅ 文件已发送给 {open_id}: {file_name}", file=sys.stderr)
    # 标准输出简洁结果，供程序化调用
    print(json.dumps({"status": "ok", "file_name": file_name, "file_key": file_key}))


if __name__ == "__main__":
    main()
