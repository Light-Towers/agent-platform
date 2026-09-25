"""会话标识解析（对齐 app/api/auth.py 已验证策略）。

安全设计：
- API_KEY 启用时，忽略客户端传入的 thread_id，改为按 API_KEY 哈希派生稳定会话
  （"user-" + sha256(API_KEY)[:12]），既防止会话劫持（客户端无法指定/猜测他人会话），
  又保证同一密钥的连续请求落到同一 thread，使 checkpointer 能跨请求复用（修复 TB-14）。
- API_KEY 未启用（开发模式，DISABLE_AUTH=true）时，信任客户端 thread_id，缺省
  "dev-default-thread"，方便本地多轮联调。
"""

import hashlib
import os

API_KEY = os.getenv("API_KEY", "")


def resolve_thread_id(client_thread_id: str | None, api_key: str | None = None) -> str:
    """解析本次请求应使用的 thread_id。

    Args:
        client_thread_id: 客户端在请求体/路径里传入的会话标识（认证期被忽略）。
        api_key: 当前请求的 API_KEY 原文（认证启用时用于派生稳定会话）。
            注意：传入 None 与传入空串等价，都按"未启用认证"处理。
    """
    if API_KEY:
        # 认证启用：按密钥派生稳定会话，忽略客户端 thread_id（防劫持）
        digest = hashlib.sha256((api_key or "").encode()).hexdigest()[:12]
        return f"user-{digest}"
    return client_thread_id or "dev-default-thread"
