"""租户哨兵门（W-2，2026-09-25）：``tenant_id`` 漏传 = fail-fast。

背景：内核与门面五动词此前签名 ``tenant_id: str = "default"``——身份传播 bug
会静默落共享 default 桶（多租户上线后即跨租户可见），而非拒绝请求。
``default`` 只保留给单租户模式的显式传参（本地开发/迁移工具），
不再作为任何一层的隐式缺省。全链上游（graph/planner/router/federation
ContextVar）已核实显式传参，故收紧无生产爆炸半径。

治理测试：``tests/governance/test_tenant_default_forbidden.py``（AST 断言
``tenant_id: str = "default"`` 形态不回潮）。
"""

from __future__ import annotations

_TENANT_UNSET = object()


def resolve_tenant(tenant_id: object) -> str:
    """校验租户显式性：哨兵（漏传）直接抛错，绝不静默降级。"""
    if tenant_id is _TENANT_UNSET:
        raise ValueError(
            "tenant_id 必须显式传入：漏传会静默落共享 default 桶"
            "（多租户下即跨租户泄漏形态，禁止）。"
            "单租户模式请显式传 tenant_id='default'。"
        )
    return tenant_id  # type: ignore[no-any-return]


__all__ = ["_TENANT_UNSET", "resolve_tenant"]
