"""测试公共工具（包内，避免 tests 包名与平台其他应用冲突）。"""

from __future__ import annotations

from typing import Any

from exhibition_agent.contract.execution_context import ExecutionContext
from exhibition_agent.middleware.context_codec import encode_base64, encode_jwt


def make_context_payload(
    *,
    user_id: str = "u-001",
    tenant_id: str = "t-sponsor-001",
    tenant_type: str = "SPONSOR",
    roles: list[str] | None = None,
    scopes: list[str] | None = None,
    auth_source: str = "PLATFORM_LOCAL",
    request_id: str = "req-0001",
) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "tenant_type": tenant_type,
        "roles": roles if roles is not None else [],
        "scopes": scopes if scopes is not None else ["exhibition:ex-001", "venue:vn-001"],
        "auth_source": auth_source,
        "request_id": request_id,
    }


def make_header(payload: dict[str, Any], *, mode: str = "jwt") -> str:
    if mode == "jwt":
        return encode_jwt(payload)
    return encode_base64(payload)


def ctx(
    *,
    tenant_id: str = "t-sponsor-001",
    tenant_type: str = "SPONSOR",
    scopes: list[str] | None = None,
    roles: list[str] | None = None,
    user_id: str = "u-001",
    request_id: str = "req-0001",
    auth_source: str = "PLATFORM_LOCAL",
) -> ExecutionContext:
    """便捷构造合法 ExecutionContext（契约 v1.1 §C1 测试便利性）。

    正常用例默认注入合法上下文（scopes 非空）；越权用例显式传 scopes=[] 触发 403。
    roles 默认留空（v1.1：角色延后，不参与判定）。
    """
    payload = make_context_payload(
        user_id=user_id,
        tenant_id=tenant_id,
        tenant_type=tenant_type,
        roles=roles,
        scopes=scopes,
        auth_source=auth_source,
        request_id=request_id,
    )
    return ExecutionContext.model_validate(payload)


def ctx_header(
    context: ExecutionContext,
    *,
    mode: str = "jwt",
) -> str:
    """把 ExecutionContext 编码成 X-Execution-Context 头值。"""
    return make_header(context.model_dump(mode="json"), mode=mode)
