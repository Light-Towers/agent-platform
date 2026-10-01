"""联邦网关身份桥接（ADR-0007 决策 2=B1）：X-Tenant-JWT 断言 → 联邦请求上下文。

复用 agent-runtime 的通用 ``IdentityMiddleware``，但把已验签租户绑定到**联邦自己的**
``api.context`` ContextVar（现有消费者如 ``knowledge_tools`` 读 ``get_tenant_context``），
避免双 ContextVar 裂脑。用**独立头 ``X-Tenant-JWT``**（决策 B1），与现有
``Authorization: Bearer <静态 API_KEY>`` 传输鉴权互不冲突、可并存渐进。
"""

from __future__ import annotations

from agent_runtime.identity_middleware import IdentityMiddleware

from api.context import reset_tenant_context, set_tenant_context


def _apply(tenant: str, user: str | None):
    # 联邦当前仅断言 tenant 进 api.context（user 断言随 A5 运行时身份接入）。
    return set_tenant_context(tenant)


def _reset(token) -> None:
    reset_tenant_context(token)


def mount_identity_middleware(app) -> None:
    """挂载 X-Tenant-JWT 租户断言中间件（验签公钥经环境配置；无令牌则 observe 透传）。"""
    app.add_middleware(
        IdentityMiddleware,
        token_header="X-Tenant-JWT",
        verify_header=None,  # 网关不采信外部 X-Internal-Tenant（那是网关→子服务的内部头）
        apply=_apply,
        reset=_reset,
    )
