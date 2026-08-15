"""认证与会话策略。

安全设计（沿用 deepagents 已验证的结论）：API_KEY 启用时忽略客户端传入的
thread_id，改为按密钥哈希派生，防止会话劫持；thread_id 仅在开发模式（未启用
API_KEY）下信任客户端。
"""

import hashlib
import secrets

from fastapi import Header, HTTPException

from app.config import get_settings


def verify_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> str | None:
    settings = get_settings()
    if not settings.api_key:
        return None  # 开发模式：不校验
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="API Key 无效")
    return x_api_key


def resolve_thread_id(client_thread_id: str | None, api_key_header: str | None) -> str:
    settings = get_settings()
    if settings.api_key:
        # 认证启用：忽略客户端 thread_id，按密钥派生稳定会话
        digest = hashlib.sha256((api_key_header or "").encode()).hexdigest()[:12]
        return f"user-{digest}"
    return client_thread_id or "dev-default-thread"
