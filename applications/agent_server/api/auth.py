"""认证与会话策略。

安全设计（沿用 deepagents 已验证的结论）：API_KEY 启用时忽略客户端传入的
thread_id，改为按**服务端断言的主体**派生，防止会话劫持；thread_id 仅在开发
模式（未启用 API_KEY）下信任客户端。

B7b-4（拆 CodeQL ``py/weak-sensitive-data-hashing`` 链①）：会话身份不再从调用方
凭据派生。旧内核函数 ``derive_thread_id``（形参即 ``api_key``）把「谁持有这把密钥」当身份熵源，
而 ``API_KEY`` 每部署一把 ⇒ 它今天本就等价于「一个部署一个桶」；换成断言租户后
桶数不变（见 ``resolve_thread_id`` docstring 的等价性说明），但凭据彻底退出派生。
派生实现仍收敛内核（DUP-1）：``agent_core.guardrails.auth.resolve_thread_identity``。
"""

import secrets

from agent_core.guardrails.auth import DEV_THREAD_ID, resolve_thread_identity
from agent_runtime.workspace_registry import server_tenant_id
from fastapi import Header, HTTPException

from agent_server.config import get_settings


def verify_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> str | None:
    settings = get_settings()
    if not settings.api_key:
        return None  # 开发模式：不校验
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="API Key 无效")
    return x_api_key


def resolve_thread_id(client_thread_id: str | None) -> str:
    """解析本次请求应使用的 thread_id（**签名里没有凭据位**，凭据在类型层面进不来）。

    :param client_thread_id: 客户端传入的会话标识，仅在开发模式被信任
    :return: 认证启用 → ``tenant-<服务端断言租户>``；开发模式 → 客户端值或
        ``DEV_THREAD_ID``
    """
    settings = get_settings()
    if settings.api_key:
        # 认证启用：忽略客户端 thread_id（防劫持），主体取服务端已断言的租户
        # （ContextVar 优先，其次部署级 default —— 与 import/sql_router、capabilities 同写法）
        return resolve_thread_identity(server_tenant_id(settings.default_tenant_id))
    return client_thread_id or DEV_THREAD_ID
