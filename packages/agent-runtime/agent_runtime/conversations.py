# -*- coding: utf-8 -*-
"""会话归属表包装器（migration 013 conversations，D11 选项 C，plan T3）。

设计约束（docs/plans/plan-platform-tenant-workspace-identity-2026-10-18.md）：

- **旁置表**：不改 checkpoints（表由 saver.setup() 外部建、INSERT 由 LangGraph
  持有）；归属断言收敛到本模块，``/history``、``/session/revert``、写线程路径
  在使用 thread_id 前经 :func:`claim_conversation` 认领。
- **单语句判据**（§9.6-5）：抢注/并发双写用 ``INSERT ... ON CONFLICT (thread_id)
  DO UPDATE ... WHERE 归属匹配 RETURNING 1``——返回 0 行即拒绝；**禁止**"先
  SELECT 判断再 INSERT"（TOCTOU）。
- **中间态口径**（§9.8）：``conversations.user_id`` 在 014b（T4 后半）前可空 ⇒
  本模块的归属匹配到 org 级；user_id 非 NULL 的行同时比对 user（014b 后收紧
  为恒比对）。不得据此宣传"会话按人隔离已具备"。
- 依赖方向：agent-runtime 层，只 stdlib + psycopg 鸭子类型池（红线 1）。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["ConversationOwnershipMismatch", "claim_conversation", "get_conversation"]


class ConversationOwnershipMismatch(PermissionError):
    """thread_id 已登记且归属不匹配（他人 org/user 的会话）：拒绝认领。"""


async def claim_conversation(
    pool: Any,
    thread_id: str,
    *,
    org_id: str,
    user_id: str | None = None,
    workspace_id: str = "",
    title: str = "",
) -> bool:
    """认领/续用会话归属（幂等 upsert，单语句防 TOCTOU）。

    - 新 thread_id ⇒ INSERT 成功，返回 True（首次认领）；
    - 已登记且归属匹配（org 等值；user_id 非 NULL 时还须 user 等值）⇒
      DO UPDATE 刷 last_active_at，返回 True；
    - 已登记但归属不匹配 ⇒ WHERE 不命中、RETURNING 0 行，抛
      :class:`ConversationOwnershipMismatch`（**不是**静默新建——thread_id 是
      全局命名空间，静默新建等于把他人会话内容接到新行上）；
    - user_id=None 的存量行：org 匹配即放行（中间态，见模块 docstring）。
    """
    if pool is None:
        return False
    if not thread_id or not isinstance(thread_id, str):
        raise ValueError("thread_id 必须为非空字符串")
    if not org_id or not isinstance(org_id, str):
        raise ValueError("org_id 必须为非空字符串")
    sql = (
        "INSERT INTO conversations (thread_id, org_id, user_id, workspace_id, title) "
        "VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (thread_id) DO UPDATE SET "
        "    last_active_at = now() "
        "WHERE conversations.org_id = EXCLUDED.org_id "
        "  AND (conversations.user_id IS NULL OR conversations.user_id = EXCLUDED.user_id) "
        "RETURNING 1"
    )
    async with pool.connection() as conn:
        cur = await conn.execute(sql, (thread_id, org_id, user_id, workspace_id, title))
        row = await cur.fetchone()
    if row is None:
        raise ConversationOwnershipMismatch(
            f"thread {thread_id!r} 已登记且归属不匹配（org={org_id!r} user={user_id!r}），"
            "拒绝跨归属认领会话（plan §9.6-5）"
        )
    return True


async def get_conversation(pool: Any, thread_id: str) -> dict[str, Any] | None:
    """读会话归属行；无登记返回 None（未迁移窗口/新线程）。"""
    if pool is None:
        return None
    sql = (
        "SELECT thread_id, org_id, user_id, workspace_id, title, created_at, last_active_at "
        "FROM conversations WHERE thread_id = %s"
    )
    async with pool.connection() as conn:
        cur = await conn.execute(sql, (thread_id,))
        row = await cur.fetchone()
    if row is None:
        return None
    keys = ("thread_id", "org_id", "user_id", "workspace_id", "title", "created_at", "last_active_at")
    return dict(zip(keys, row))
