"""V3-3 PG 持久化后端：execution_status / awaitable_tasks。

- ``PgExecutionStatusStore``  → execution_status（durable status state machine）
- ``PgAwaitableTaskStore``    → awaitable_tasks（External / Human / Timer / Callback）

遵循 §20 生产级约束：所有状态变更为单条 SQL 原子 CAS；状态机转换校验在 Python 层
（先 load 后判），generation fencing 在 SQL 层原子保证。
"""

from __future__ import annotations

import json
from typing import Any

from agent_runtime.awaitable_task import (
    AwaitableKind,
    AwaitableState,
    AwaitableTask,
    AwaitableTaskStore,
    InvalidTaskTransition,
)
from agent_runtime.awaitable_task import (
    can_transition as can_task_transition,
)
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


class PgAwaitableTaskStore(AwaitableTaskStore):
    """PG 可等待任务存储：awaitable_tasks 表。"""

    def __init__(self, pool: Any, *, table: str = "awaitable_tasks") -> None:
        self._pool = pool
        self._table = table

    @staticmethod
    def _row_to_task(row: tuple) -> AwaitableTask:
        (
            task_id,
            execution_id,
            step_id,
            kind,
            provider,
            state,
            provider_task_id,
            submission_receipt,
            completion_receipt,
            submitted_at,
            completed_at,
            deadline,
            resume_payload,
            metadata,
            updated_at,
        ) = row
        return AwaitableTask(
            execution_id=execution_id,
            step_id=step_id,
            kind=AwaitableKind(kind),
            provider=provider,
            task_id=task_id,
            state=AwaitableState(state),
            provider_task_id=provider_task_id,
            submission_receipt=_loads(submission_receipt),
            completion_receipt=_loads(completion_receipt),
            submitted_at=submitted_at,
            completed_at=completed_at,
            deadline=deadline,
            resume_payload=_loads(resume_payload),
            metadata=_loads(metadata) if metadata is not None else {},
            updated_at=updated_at,
        )

    _COLS = (
        "task_id, execution_id, step_id, kind, provider, state, provider_task_id, "
        "submission_receipt, completion_receipt, submitted_at, completed_at, deadline, "
        "resume_payload, metadata, updated_at"
    )

    async def save(self, task: AwaitableTask) -> None:
        cur = await self.load(task.task_id)
        if cur is not None and not can_task_transition(cur.state, task.state):
            raise InvalidTaskTransition(
                f"非法任务状态转换: {cur.state.value} → {task.state.value} (task={task.task_id})"
            )
        sql = (
            f"INSERT INTO {self._table} ({self._COLS}) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (task_id) DO UPDATE "
            "SET state = EXCLUDED.state, provider_task_id = EXCLUDED.provider_task_id, "
            "    submission_receipt = EXCLUDED.submission_receipt, "
            "    completion_receipt = EXCLUDED.completion_receipt, "
            "    submitted_at = EXCLUDED.submitted_at, completed_at = EXCLUDED.completed_at, "
            "    deadline = EXCLUDED.deadline, resume_payload = EXCLUDED.resume_payload, "
            "    metadata = EXCLUDED.metadata, updated_at = EXCLUDED.updated_at"
        )
        async with self._pool.connection() as conn:
            await conn.execute(
                sql,
                (
                    task.task_id,
                    task.execution_id,
                    task.step_id,
                    task.kind.value,
                    task.provider,
                    task.state.value,
                    task.provider_task_id,
                    _dumps(task.submission_receipt),
                    _dumps(task.completion_receipt),
                    task.submitted_at,
                    task.completed_at,
                    task.deadline,
                    _dumps(task.resume_payload),
                    _dumps(task.metadata),
                    task.updated_at,
                ),
            )

    async def load(self, task_id: str) -> AwaitableTask | None:
        sql = f"SELECT {self._COLS} FROM {self._table} WHERE task_id = %s"
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql, (task_id,))
            row = await cur.fetchone()
        return self._row_to_task(row) if row is not None else None

    async def list_by_execution(self, execution_id: str) -> list[AwaitableTask]:
        sql = f"SELECT {self._COLS} FROM {self._table} WHERE execution_id = %s"
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql, (execution_id,))
            rows = await cur.fetchall()
        return [self._row_to_task(r) for r in rows]

    async def list_unresolved(self) -> list[AwaitableTask]:
        terminal = tuple(s.value for s in AwaitableState if s.is_terminal)
        placeholders = ", ".join(["%s"] * len(terminal))
        sql = f"SELECT {self._COLS} FROM {self._table} WHERE state NOT IN ({placeholders})"
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql, terminal)
            rows = await cur.fetchall()
        return [self._row_to_task(r) for r in rows]


__all__ = ["PgExecutionStatusStore", "PgAwaitableTaskStore"]