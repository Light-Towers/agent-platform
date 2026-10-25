"""V3-3 PG 持久化后端：execution_status。

- ``PgExecutionStatusStore``  → execution_status（durable status state machine）

遵循 §20 生产级约束：所有状态变更为单条 SQL 原子 CAS，generation fencing 在 SQL 层原子保证。

**去重记录（2026-10-16，roadmap 阶段1 #4 判据「同名实现只剩一处」）**：本模块原另有一份
``PgAwaitableTaskStore``，与 ``awaitable_task_pg.py`` 里那份同名、同继承 ``AwaitableTaskStore``，
但它 **不含 generation fence**（``save`` 的 INSERT 只写 15 列、`generation` 留空、无 WHERE 守卫），
且零生产调用。留着它的风险不是冗余：本模块是「 Pg 存储」的自然 import 点，谁从这儿取就用到了
无防护那份，``68a44290`` 补的 fence 会静默退化。唯一实现 = ``agent_runtime.awaitable_task_pg.PgAwaitableTaskStore``。
"""

from __future__ import annotations

import json
from typing import Any

from agent_runtime.execution_status import (
    ExecutionStatus,
    ExecutionStatusRecord,
    ExecutionStatusStore,
    InvalidStatusTransition,
    can_transition,
)


def _dumps(obj: Any) -> str | None:
    if obj is None:
        return None
    return json.dumps(obj, ensure_ascii=False, default=str)


def _loads(val: Any) -> Any:
    if isinstance(val, str):
        return json.loads(val)
    return val


class PgExecutionStatusStore(ExecutionStatusStore):
    """PG execution status 存储：execution_status 表。

    字段：execution_id PK / status / generation / reason / metadata / updated_at。
    """

    def __init__(self, pool: Any, *, table: str = "execution_status") -> None:
        self._pool = pool
        self._table = table

    async def load(self, execution_id: str) -> ExecutionStatusRecord | None:
        sql = (
            f"SELECT status, generation, reason, metadata, updated_at "
            f"FROM {self._table} WHERE execution_id = %s"
        )
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql, (execution_id,))
            row = await cur.fetchone()
        if row is None:
            return None
        status, generation, reason, metadata, updated_at = row
        return ExecutionStatusRecord(
            execution_id=execution_id,
            status=ExecutionStatus(status),
            generation=generation,
            reason=reason or "",
            metadata=_loads(metadata) if metadata is not None else {},
            updated_at=updated_at,
        )

    async def save(self, record: ExecutionStatusRecord) -> None:
        cur = await self.load(record.execution_id)
        if cur is not None and not can_transition(cur.status, record.status):
            raise InvalidStatusTransition(
                f"非法状态转换: {cur.status.value} → {record.status.value} "
                f"(execution={record.execution_id})"
            )
        sql = (
            f"INSERT INTO {self._table} "
            "(execution_id, status, generation, reason, metadata, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (execution_id) DO UPDATE "
            "SET status = EXCLUDED.status, generation = EXCLUDED.generation, "
            "    reason = EXCLUDED.reason, metadata = EXCLUDED.metadata, "
            "    updated_at = EXCLUDED.updated_at "
            "WHERE (EXCLUDED.generation IS NULL OR {table}.generation IS NULL "
            "       OR EXCLUDED.generation >= {table}.generation) "
            "RETURNING execution_id"
        ).format(table=self._table)
        async with self._pool.connection() as conn:
            cur2 = await conn.execute(
                sql,
                (
                    record.execution_id,
                    record.status.value,
                    record.generation,
                    record.reason,
                    _dumps(record.metadata),
                    record.updated_at,
                ),
            )
            if await cur2.fetchone() is None:
                raise InvalidStatusTransition(
                    f"状态写入被 generation fencing 拒绝: record generation="
                    f"{record.generation} (execution={record.execution_id})"
                )
