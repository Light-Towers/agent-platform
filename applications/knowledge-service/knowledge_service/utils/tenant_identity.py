"""knowledge-service 侧内部签名头租户断言（ADR-0007 A3/A4，决策 1=A3）。

用 **agent-core 共享原语**校验网关下发的 ``X-Internal-Tenant`` HMAC 头，绑定到本服务请求
ContextVar，供 :func:`knowledge_service.utils.tenant_utils.resolve_server_tenant` 优先采信。

- 纯 ASGI，只读 ``scope`` headers，不消费请求体（无 FastAPI/Starlette 依赖，ks 不需新增 agent-runtime）；
- 收到**伪造**内部头（配置了密钥却验签失败）= 明确攻击信号 → 401（无合法理由发伪造头）；
- 缺头 / 未配密钥（开发态）→ 透传，由 resolve_server_tenant 走 provided>default（A6 弃用后收紧）。
"""

from __future__ import annotations

import json
import os
from contextvars import ContextVar
from typing import Awaitable, Callable

from agent_core.internal_header import InternalHeaderError, load_hmac_key, verify_internal_header

__all__ = [
    "TenantHeaderMiddleware",
    "current_asserted_tenant",
    "bind_asserted_tenant",
    "reset_asserted_tenant",
]

_asserted_tenant: ContextVar[str | None] = ContextVar("ks_asserted_tenant", default=None)


def current_asserted_tenant() -> str | None:
    return _asserted_tenant.get()


def bind_asserted_tenant(tenant: str | None):
    return _asserted_tenant.set(tenant)


def reset_asserted_tenant(token) -> None:
    _asserted_tenant.reset(token)


def _header(scope: dict, name: str) -> str | None:
    target = name.lower().encode()
    for key, value in scope.get("headers", []):
        if key.lower() == target:
            return value.decode()
    return None


async def _send_json(send: Callable[[dict], Awaitable[None]], status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send({
        "type": "http.response.start", "status": status,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
    })
    await send({"type": "http.response.body", "body": body})


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    return default if not raw else raw.strip().lower() in ("1", "true", "yes", "on")


def _max_age() -> int:
    try:
        return int(os.getenv("INTERNAL_HEADER_MAX_AGE_S", "300"))
    except ValueError:
        return 300


class TenantHeaderMiddleware:
    def __init__(
        self,
        app: Callable[[dict, Callable, Callable], Awaitable[None]],
        *,
        enforce_missing: bool | None = None,
    ) -> None:
        self.app = app
        # A6 灰度末开：无合法内部头即拒（fail-closed）。A4 观测期默认关（缺头透传）。
        self._enforce_missing = (
            _env_bool("TENANT_HEADER_ENFORCE", False) if enforce_missing is None else enforce_missing
        )

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        hdr = _header(scope, "X-Internal-Tenant")
        key = load_hmac_key()
        if hdr and key:
            try:
                result = verify_internal_header(hdr, key=key, max_age=_max_age())
            except InternalHeaderError as e:
                await _send_json(send, 401, f"内部签名头无效: {e}")
                return
            if result is not None:
                tenant, _user = result
                token = bind_asserted_tenant(tenant)
                try:
                    await self.app(scope, receive, send)
                finally:
                    reset_asserted_tenant(token)
                return
        # 无合法断言：缺失且强制 → 拒；否则透传（provided>default 既有语义）
        if self._enforce_missing and not hdr:
            await _send_json(send, 401, "缺少 X-Internal-Tenant 内部签名头（TENANT_HEADER_ENFORCE）")
            return
        await self.app(scope, receive, send)
