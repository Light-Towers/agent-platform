"""身份断言中间件（ADR-0007 A3/A4）：纯 ASGI、框架无关，从头部解析租户并绑定上下文。

置于 agent-runtime（身份中间件层，随 ``identity`` extra）；不 import FastAPI/Starlette——只读
ASGI ``scope`` 的 headers，绝不消费请求体（避免 receive 缓冲问题；body 里的 ``tenant_id`` 由 A5
双读在路由层处理）。**ContextVar 绑定在本中间件内 set/reset**，纯 ASGI 与端点共享上下文，故
下游 ``server_tenant_id()`` / A2 的 ``_sanitize_identity`` 能读到真实断言租户。

挂载：
- **网关 / agent_server**：验签 ``Authorization: Bearer <RS256 JWT>`` → 绑定 tenant/user。
- **子服务（knowledge-service 等）**：验签 ``X-Internal-Tenant`` HMAC 头（软模式：缺→软/硬，伪造→拒）。

行为（信任边界，observe 默认）：
1. 有合法 Bearer → 绑定，放行。
2. Bearer 非法/过期 → 401（fail-closed）。
3. 有合法内部签名头 → 绑定，放行；头伪造 → 401。
4. 无任何凭据 → 部署 ``SINGLE_TENANT`` 则绑定之（软）；否则 observe 模式交路由既有逻辑
   （provided>default，兼容存量），``TENANT_JWT_ENFORCE=true`` 则 401。
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from agent_runtime.identity import (
    IdentityError,
    apply_tenant_context,
    env_bool,
    extract_bearer,
    resolve_startup_tenant_mode,
    verify_internal_header,
    verify_token,
)
from agent_runtime.workspace_registry import reset_tenant_context, reset_user_context

__all__ = ["IdentityMiddleware"]

_Verify = Callable[[str], Any]  # token -> TokenClaims
_Apply = Callable[[str, "str | None"], Any]  # (tenant, user) -> tokens
_Reset = Callable[[Any], None]


def _verify_header_value(value: str):
    """内部签名头校验器（接受头值字符串）：返回 (tenant, user)，伪造/过期抛 IdentityError。"""
    return verify_internal_header(value)


def _header(scope: dict, name: str) -> str | None:
    target = name.lower().encode()
    for key, value in scope.get("headers", []):
        if key.lower() == target:
            return value.decode()
    return None


def _looks_like_jwt(token: str) -> bool:
    """JWT 形态判断：三段 `.` 分隔且 header 段 base64url 以 `eyJ` 开头（`{"` 编码）。

    区分“真正的租户 JWT”与“不透明 Bearer（如某些部署把静态 API_KEY 放 Authorization）”：
    后者不是本中间件的凭据 → 交下游既有认证，避免误拒。
    """
    parts = token.split(".")
    return len(parts) == 3 and parts[0].startswith("eyJ")


async def _send_json(send: Callable[[dict], Awaitable[None]], status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": body})


class IdentityMiddleware:
    def __init__(
        self,
        app: Callable[[dict, Callable, Callable], Awaitable[None]],
        *,
        verify: _Verify | None = None,
        apply: _Apply = apply_tenant_context,
        reset: _Reset | None = None,
        verify_header: Callable | None = _verify_header_value,
        token_header: str = "Authorization",
        enforce_missing: bool | None = None,
        single_tenant: str | None | Callable[[], str | None] = None,
        skip_paths: tuple[str, ...] = ("/health", "/healthz", "/metrics", "/docs", "/openapi.json", "/redoc", "/ws"),
    ) -> None:
        self.app = app
        self._verify = verify or verify_token
        self._apply = apply
        self._reset = reset or self._default_reset
        self._verify_header = verify_header
        self._token_header = token_header
        # enforce 默认读环境 TENANT_JWT_ENFORCE（子服务软模式设 verify_header + 环境不置 enforce 即可）
        self._enforce_missing = env_bool("TENANT_JWT_ENFORCE", False) if enforce_missing is None else enforce_missing
        self._single_tenant = single_tenant
        self._skip = skip_paths

    @staticmethod
    def _default_reset(tokens) -> None:
        tenant_token, user_token = tokens
        reset_tenant_context(tenant_token)
        reset_user_context(user_token)

    def _resolve_single(self) -> str | None:
        if callable(self._single_tenant):
            return self._single_tenant()
        if self._single_tenant is not None:
            return self._single_tenant
        mode, tenant = resolve_startup_tenant_mode()
        return tenant if mode == "single" else None

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope.get("type") != "http" or scope.get("path", "") in self._skip:
            await self.app(scope, receive, send)
            return

        raw = _header(scope, self._token_header)
        if self._token_header.lower() == "authorization":
            # Authorization：仅当 Bearer 形如 JWT 才当租户凭据；不透明 Bearer（静态 API_KEY）交下游既有认证。
            bearer = extract_bearer(raw)
            is_credential = bool(bearer) and _looks_like_jwt(bearer)
        else:
            # 专用头（如 X-Tenant-JWT）：存在即视为租户 JWT。
            bearer = raw
            is_credential = bool(bearer)
        if is_credential and bearer:
            try:
                claims = self._verify(bearer)
            except IdentityError as e:
                await _send_json(send, 401, f"身份令牌无效: {e}")
                return
            await self._run(claims.tenant_id, claims.user_id, scope, receive, send)
            return

        if self._verify_header is not None:
            hdr = _header(scope, "X-Internal-Tenant")
            if hdr:
                try:
                    result = self._verify_header(hdr)
                except IdentityError as e:
                    await _send_json(send, 401, f"内部签名头无效: {e}")
                    return
                if result is not None:
                    tenant, user = result
                    await self._run(tenant, user, scope, receive, send)
                    return

        single = self._resolve_single()
        if single:
            await self._run(single, None, scope, receive, send)
            return

        if self._enforce_missing:
            await _send_json(send, 401, "缺少身份凭据（TENANT_JWT_ENFORCE）")
            return
        # observe：无凭据交下游（路由 provided>default 既有语义）
        await self.app(scope, receive, send)

    async def _run(self, tenant: str, user: str | None, scope: dict, receive: Callable, send: Callable) -> None:
        tokens = self._apply(tenant, user)
        try:
            await self.app(scope, receive, send)
        finally:
            self._reset(tokens)
