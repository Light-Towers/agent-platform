"""租户/工作区作用域解析（§5.9 / P1-1 / A 方案前置）：召回与多轮状态的隔离边界。

**为什么需要**：nl2sql 此前从**客户端请求体**取 `tenant_id` 且不用于召回过滤——
既违反 ADR-0007（身份须服务端断言，客户端 body 可伪造），也无隔离（召回面向
全库）。这是收敛 A 方案（agent_server/sql 退役统一到 nl2sql）的硬前置：
agent_server/sql 已按 ADR-0006 做 tenant 隔离，nl2sql 不补就是净倒退。

**解析优先级**（对齐 `agent_runtime.identity.resolve_tenant_context`，ADR-0007）：
1. **服务端断言**（身份门 ContextVar，JWT / 内部签名头）——最高，客户端改不了；
2. 客户端 `provided`（请求体 tenant_id）——仅无断言时兜底；
3. `default`（settings.default_tenant）——单租户 dev 缺省，**非静默**：
   enforce 档（TENANT_JWT_ENFORCE）下不给 default，走 fail-fast，不静默落共享桶。

**向后兼容**：单租户 dev（无断言、无请求租户、default_tenant=''）解析出 ''，
与既有 meta 行的 tenant_id='' 匹配，行为逐字节不变。workspace 是归属细维
（ADR-0006 W1），同套优先级；其注册表校验（resolve_workspace）属后续细化，
本模块只做**作用域值的解析与透传**，不做 workspace 存在性断言。
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_runtime.identity import resolve_tenant_context


@dataclass(frozen=True)
class TenantScope:
    """一次查询的隔离作用域。空串 = 单租户 dev（匹配 DDL 默认 '' 行）。"""

    tenant_id: str
    workspace_id: str


def resolve_scope(
    *,
    request_tenant: str | None,
    request_workspace: str | None,
    default_tenant: str = "",
    default_workspace: str = "",
) -> TenantScope:
    """解析 (tenant_id, workspace_id)。

    - tenant：服务端断言 > 请求体 > default_tenant（空 = 单租户 dev；enforce 档
      由调用方传 default_tenant=_TENANT_UNSET 触发 fail-fast）。
    - workspace：无独立 ContextVar 断言路径，取请求体 > default_workspace。
    """
    tenant = resolve_tenant_context(provided=request_tenant, default=default_tenant)
    workspace = (request_workspace or "").strip() or (default_workspace or "")
    return TenantScope(tenant_id=tenant, workspace_id=workspace)


__all__ = ["TenantScope", "resolve_scope"]
