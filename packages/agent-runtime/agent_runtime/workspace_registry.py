# -*- coding: utf-8 -*-
"""Workspace 归属注册表 + 服务端租户上下文（ADR-0006 D1/D4 方案 A，plan T9/T10）。

隔离域契约（`docs/adr/0006-isolation-dimension-contract.md`）：

- ``tenant_id`` 是**唯一安全边界**：值由服务端解析（请求链路 ContextVar /
  部署配置），客户端不可指定；本模块的 ``server_tenant_id()`` 是该边界的
  单一取值点，语义沿用 ``agent_core.memory._tenant_gate.resolve_tenant``
  ——漏绑定 fail-fast，绝不静默落共享 ``default`` 桶（归属不明宁可不可见）。
- ``workspace_id`` 是**归属维度**（客户端可传），不可单独承担隔离职责。
  ``workspaces`` 归属表（migration 007）证明 workspace 的租户归属：
  首次引用自动注册到调用方租户；workspace id 按租户命名空间化
  （复合 PK ``(tenant_id, id)``），跨租户同名物理上互不相干。

依赖方向：本模块属 agent-runtime（PaaS 层），只 stdlib + psycopg 鸭子类型池，
不 import 任何 application（红线 1）。宿主（agent_server）在 lifespan/依赖中
``bind_tenant_context()``，写入/读取端点在使用 workspace_id 前先 ``resolve_workspace``。
"""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token

from agent_core.memory._tenant_gate import _TENANT_UNSET, resolve_tenant

logger = logging.getLogger(__name__)

# 请求链路租户上下文（服务端绑定，与 agent_federation/api/context.py 同构）。
# default=None：未绑定即读取 = 漏接线，resolve 时 fail-fast，不给隐式缺省。
_tenant_id_ctx: ContextVar[object] = ContextVar("server_tenant_id", default=_TENANT_UNSET)

__all__ = [
    "WorkspaceTenantMismatch",
    "bind_tenant_context",
    "reset_tenant_context",
    "resolve_workspace",
    "register_workspace",
    "assert_workspace_access",
    "server_tenant_id",
]


class WorkspaceTenantMismatch(PermissionError):
    """workspace_id 已归属其他租户：拒绝跨租户引用（ADR-0006 D4）。"""


# --- 服务端租户上下文 -------------------------------------------------------

def bind_tenant_context(tenant_id: str) -> Token:
    """绑定当前执行上下文（请求）的服务端租户；返回 Token 供复位。"""
    return _tenant_id_ctx.set(resolve_tenant(tenant_id))


def reset_tenant_context(token: Token) -> None:
    _tenant_id_ctx.reset(token)


def server_tenant_id(default: object = _TENANT_UNSET) -> str:
    """解析服务端租户：ContextVar 优先，其次调用方显式传入的部署级 default。

    两者都缺 → 抛错（fail-fast）。``default`` 参数仅接受显式实参
    （如 agent_server 的 ``DEFAULT_TENANT_ID`` 配置），无隐式值。
    """
    bound = _tenant_id_ctx.get()
    if bound is not _TENANT_UNSET:
        return bound  # type: ignore[no-any-return]
    return resolve_tenant(default)


def _require_tenant(tenant_id: object) -> str:
    tenant = resolve_tenant(tenant_id)
    if not isinstance(tenant, str) or not tenant.strip():
        raise ValueError("tenant_id 必须为非空字符串")
    return tenant


def _require_workspace_id(workspace_id: object) -> str:
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        raise ValueError("workspace_id 必须为非空字符串")
    if len(workspace_id) > 128:
        raise ValueError("workspace_id 超长（>128）")
    return workspace_id


def _is_undefined_table(exc: BaseException) -> bool:
    """仅判定 PG 错误码 42P01（undefined_table）：渐进部署窗口内 007 可能未应用。

    真故障（连接断/超时/权限）不得归入「表缺失」降级放行——那是 fail-open。
    """
    return getattr(exc, "sqlstate", None) == "42P01"


# --- 归属校验（migration 007 workspaces 表） --------------------------------

async def resolve_workspace(pool, tenant_id: object, workspace_id: str) -> bool:
    """使用 workspace_id 前的归属解析：确保 ``(tenant_id, workspace_id)`` 存在，
    不存在则按调用方租户自动注册（首次引用），幂等。返回 True 表示可安全读写。

    语义（ADR-0006 D4 方案 A，复合 PK ``(tenant_id, id)`` 按租户命名空间化）：
    - 同一 workspace_id 字符串在不同租户各自一行 → 跨租户“同名”是两个独立
      workspace，本函数只登记调用方自己的那一行，不触碰他租户（禁止共享行）；
    - 当前 workspace_id 为客户端传入的扁平字符串（如 'default'）且非全局唯一，
      故必须命名空间化而非以 id 全局唯一为 PK（否则 'default' 跨租户撞 PK）；
    - 表未应用（渐进部署窗口）→ 返回 True 降级（数据读写仍由 tenant 谓词兜底）；
    - 入参非法（空/超长/漏传 tenant）→ fail-fast 抛错。
    """
    tenant = _require_tenant(tenant_id)
    ws = _require_workspace_id(workspace_id)
    await register_workspace(pool, ws, tenant)
    return True


async def register_workspace(pool, workspace_id: str, tenant_id: object) -> None:
    """写入前归属校验/注册：首次引用自动注册到调用方租户（幂等）。

    - 本租户已注册 → no-op；
    - 未注册 → INSERT（复合 PK ``(tenant_id, id)`` 下并发竞态只会发生在本
      租户内，ON CONFLICT DO NOTHING 即幂等）；
    - 表不存在（migration 007 未应用）→ 降级放行并告警：数据谓词已含
      tenant_id（migration 006），归属表是 defense-in-depth，不因其缺失
      阻断写入（渐进部署窗口）。
    """
    if pool is None:
        return
    tenant = _require_tenant(tenant_id)
    ws = _require_workspace_id(workspace_id)
    try:
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT 1 FROM workspaces WHERE tenant_id = %s AND id = %s",
                (tenant, ws),
            )
            if await cur.fetchone():
                return
            await conn.execute(
                "INSERT INTO workspaces (tenant_id, id) VALUES (%s, %s) "
                "ON CONFLICT (tenant_id, id) DO NOTHING",
                (tenant, ws),
            )
    except Exception as e:
        if _is_undefined_table(e):
            logger.warning(
                "workspaces 归属表不存在（migration 007 未应用），注册跳过：%s:%s",
                tenant, ws,
            )
            return
        raise


async def assert_workspace_access(pool, workspace_id: str, tenant_id: object) -> None:
    """读取前归属断言：workspace 已注册但属其他租户 → WorkspaceTenantMismatch。

    未注册（含 007 未应用）放行——读结果本身已被 tenant 谓词约束（006），
    本断言拦截的是「显式越权引用」而非做数据兜底（宁可不可见，不跨租户可见）。
    """
    if pool is None:
        return
    tenant = _require_tenant(tenant_id)
    ws = _require_workspace_id(workspace_id)
    try:
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT tenant_id FROM workspaces WHERE id = %s", (ws,)
            )
            rows = await cur.fetchall()
    except Exception as e:
        if _is_undefined_table(e):
            return
        raise
    owners = {r[0] for r in rows}
    if owners and tenant not in owners:
        raise WorkspaceTenantMismatch(
            f"workspace {ws!r} 已归属其他租户，拒绝跨租户访问（ADR-0006 D4）"
        )
