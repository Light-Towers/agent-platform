# -*- coding: utf-8 -*-
"""多会话目录服务（服务端签发的会话 id + 归属断言）。

设计红线（与 D-l 一脉相承，务必先读）：
- **不碰 ``resolve_thread_id`` 的基础语义**：认证模式下它把客户端值当劫持面忽略，
  由服务端断言主体派生 thread_id。本模块在其返回值后**追加一段服务端签发的会话后缀**，
  前缀仍是断言主体 ⇒ 客户端再怎么猜 session_id 也落不到他人名下（跨租户/跨人隔离
  由前缀保证，与 D-l 同源）。
- **session_id 由服务端签发**（uuid4），不是客户端自报；客户端只持有服务端发回的 id。
  任何读写前按 (session_id, org_id, user_id) 校验归属（见 :func:`get_session`）——
  会话 id 猜中也不能越权。
- **存量兼容**：未走本模块（无 session_id / 校验不通过）的路径 thread_id 逐字不变，
  治理测试钉死的 D-l 行为完全不动。

数据基础：migration 018 的 ``agent_sessions`` 旁置表（启动自动建），本模块独占读写。
"""

from __future__ import annotations

import uuid
from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)

SESSION_THREAD_SEP = "--session-"
"""thread_id 后缀分隔符。落在 resolve_thread_identity 白名单 [A-Za-z0-9._-] 内，
不会被 safe_filename 有损改写，故不会与另一主体/会话碰撞。"""

_SESSION_COLS = (
    "session_id, org_id, user_id, thread_id, title, workspace_id, created_at, last_active_at"
)


class SessionNotFound(Exception):
    """会话不存在或归属不匹配（对端点映射 404，不泄露"存在但非你所有"）。"""


def new_session_id() -> str:
    """服务端签发会话 id（uuid4 hex，filename-safe，不含分隔符/大写歧义）。"""
    return uuid.uuid4().hex


def is_session_id(value: str | None) -> bool:
    """是否形如服务端签发的会话 id（32 位 hex）。仅用于快速分流，归属仍要查库。"""
    if not value or len(value) != 32:
        return False
    return all(c in "0123456789abcdef" for c in value)


def session_thread_id(base_thread_id: str, session_id: str) -> str:
    """会话专属 thread_id = 断言主体派生值 + 会话后缀。

    :param base_thread_id: :func:`resolve_thread_id(None)` 的返回值（断言主体）
    :param session_id: 服务端签发的会话 id
    ⚠ 调用方必须已完成归属校验；本函数仅做字符串派生，不查库。
    """
    return f"{base_thread_id}{SESSION_THREAD_SEP}{session_id}"


def _row_to_dict(row: Any) -> dict[str, Any]:
    keys = (
        "session_id", "org_id", "user_id", "thread_id", "title",
        "workspace_id", "created_at", "last_active_at",
    )
    d = dict(zip(keys, row))
    for k in ("created_at", "last_active_at"):
        if d.get(k) is not None and not isinstance(d[k], str):
            d[k] = d[k].isoformat()
    return d


async def create_session(
    pool: Any,
    *,
    org_id: str,
    user_id: str,
    base_thread_id: str,
    workspace_id: str = "",
    title: str = "",
) -> dict[str, Any]:
    """签一个新会话并落归属行，返回会话字典。pool 为空时拒绝（多会话需持久化）。"""
    if pool is None:
        raise RuntimeError("多会话需要数据库连接池（agent_sessions 持久化）")
    session_id = new_session_id()
    thread_id = session_thread_id(base_thread_id, session_id)
    sql = (
        "INSERT INTO agent_sessions "
        "(session_id, org_id, user_id, thread_id, title, workspace_id) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING " + _SESSION_COLS
    )
    async with pool.connection() as conn:
        cur = await conn.execute(
            sql, (session_id, org_id, user_id, thread_id, title, workspace_id)
        )
        row = await cur.fetchone()
    return _row_to_dict(row)


async def get_session(pool: Any, session_id: str, *, org_id: str, user_id: str) -> dict[str, Any] | None:
    """按 (session_id, org_id, user_id) 精确校验归属取会话；不匹配/不存在 → None。

    user_id 用断言的原始值（JWT sub 或 user_id claim）精确比对，空串表示无「人」断言
    （dev/租户级令牌）——此时与表里 user_id='' 的行匹配，org 内可见，不跨 org。
    """
    if pool is None or not session_id:
        return None
    sql = f"SELECT {_SESSION_COLS} FROM agent_sessions WHERE session_id=%s AND org_id=%s AND user_id=%s"
    async with pool.connection() as conn:
        cur = await conn.execute(sql, (session_id, org_id, user_id))
        row = await cur.fetchone()
    return _row_to_dict(row) if row is not None else None


async def resolve_session_thread(
    pool: Any, session_id: str | None, *, org_id: str, user_id: str
) -> str | None:
    """session_id 是合法已登记会话 → 返回其派生 thread_id；否则 None（走存量逻辑）。

    先做形态快筛（uuid hex），再查库校验归属——两步都过才切换 thread_id。
    """
    if not is_session_id(session_id):
        return None
    row = await get_session(pool, session_id, org_id=org_id, user_id=user_id)
    return row["thread_id"] if row is not None else None


async def list_sessions(pool: Any, *, org_id: str, user_id: str) -> list[dict[str, Any]]:
    """列当前归属人的会话（last_active_at 降序），不含 thread_id 之外的敏感信息。"""
    if pool is None:
        return []
    sql = (
        f"SELECT {_SESSION_COLS} FROM agent_sessions "
        "WHERE org_id=%s AND user_id=%s ORDER BY last_active_at DESC LIMIT 100"
    )
    async with pool.connection() as conn:
        cur = await conn.execute(sql, (org_id, user_id))
        rows = await cur.fetchall()
    return [_row_to_dict(r) for r in rows]


async def touch_session(pool: Any, session_id: str, *, org_id: str, user_id: str) -> None:
    """刷新会话活跃时间（best-effort，失败不影响主流程）。"""
    if pool is None:
        return
    sql = (
        "UPDATE agent_sessions SET last_active_at=now() "
        "WHERE session_id=%s AND org_id=%s AND user_id=%s"
    )
    try:
        async with pool.connection() as conn:
            await conn.execute(sql, (session_id, org_id, user_id))
    except Exception as exc:  # noqa: BLE001 —— 活跃时间刷新失败不阻断对话，best-effort 且留日志
        logger.warning("touch_session 失败 session=%s: %s", session_id, exc)


async def delete_session(pool: Any, session_id: str, *, org_id: str, user_id: str) -> bool:
    """删除归属匹配的会话行；返回是否删到（0 行 = False → 端点映射 404）。"""
    if pool is None:
        return False
    sql = "DELETE FROM agent_sessions WHERE session_id=%s AND org_id=%s AND user_id=%s"
    async with pool.connection() as conn:
        cur = await conn.execute(sql, (session_id, org_id, user_id))
    return (cur.rowcount or 0) > 0
