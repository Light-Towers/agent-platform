"""PG 持久化 AwaitableTaskStore（V3 Phase 3）。

与 ``InMemoryAwaitableTaskStore`` 同接口，状态转换校验在应用层做（load → check → save），
PG 只做持久化。DDL 见 ``db.py``C`` 的 ``awaitable_tasks`` 表。
"""

from __future__ import annotations

import json
import time
from typing import Any

from agent_runtime.awaitable_task import (
    AwaitableKind,
    AwaitableState,
    AwaitableTask,
    AwaitableTaskStore,
    InvalidTaskTransition,
    can_transition,
)


class PgAwaitableTaskStore(AwaitableTaskStore):
    """PG 持久化可等待任务存储。"""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def save(self, task: AwaitableTask) -> None:
        cur = await self.load(task.task_id)
        if cur is not None and not can_transition(cur.state, task.state):
            raise InvalidTaskTransition(
                f"非法任务状态转换: {cur.state.value} → {task.state.value} (task={task.task_id})"
            )
        task.updated_at = time.time()
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO awaitable_tasks "
                "(task_id, execution_id, step_id, kind, provider, state, "
                " provider_task_id, submission_receipt, completion_receipt, "
                " submitted_at, completed_at, deadline, resume_payload, metadata, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (task_id) DO UPDATE SET "
                " execution_id = EXCLUDED.execution_id, "
                " step_id = EXCLUDED.step_id, "
                " kind = EXCLUDED.kind, "
                " provider = EXCLUDED.provider, "
                " state = EXCLUDED.state, "
                " provider_task_id = EXCLUDED.provider_task_id, "
                " submission_receipt = EXCLUDED.submission_receipt, "
                " completion_receipt = EXCLUDED.completion_receipt, "
                " submitted_at = EXCLUDED.submitted_at, "
                " completed_at = EXCLUDED.completed_at, "
                " deadline = EXCLUDED.deadline, "
                " resume_payload = EXCLUDED.resume_payload, "
                " metadata = EXCLUDED.metadata, "
                " updated_at = EXCLUDED.updated_at",
                (
                    task.task_id,
                    task.execution_id,
                    task.step_id,
                    task.kind.value,
                    task.provider,
                    task.state.value,
                    task.provider_task_id,
                    json.dumps(task.submission_receipt) if task.submission_receipt else None,
                    json.dumps(task.completion_receipt) if task.completion_receipt else None,
                    task.submitted_at,
                    task.completed_at,
                    task.deadline,
                    json.dumps(task.resume_payload) if task.resume_payload else None,
                    json.dumps(task.metadata),
                    task.updated_at,
                ),
            )

    async def load(self, task_id: str) -> AwaitableTask | None:
        async with self._pool.connection() as conn:
            row = await conn.execute(
                "SELECT task_id, execution_id, step_id, kind, provider, state, "
                "       provider_task_id, submission_receipt, completion_receipt, "
                "       submitted_at, completed_at, deadline, resume_payload, metadata, updated_at "
                "FROM awaitable_tasks WHERE task_id = %s",
                (task_id,),
            )
            r = await row.fetchone()
            if not r:
                return None
            return self._row_to_task(r)

    async def list_by_execution(self, execution_id: str) -> list[AwaitableTask]:
        async with self._pool.connection() as conn:
            row = await conn.execute(
                "SELECT task_id, execution_id, step_id, kind, provider, state, "
                "       provider_task_id, submission_receipt, completion_receipt, "
                "       submitted_at, completed_at, deadline, resume_payload, metadata, updated_at "
                "FROM awaitable_tasks WHERE execution_id = %s",
                (execution_id,),
            )
            rows = await row.fetchall()
            return [self._row_to_task(r) for r in rows]

    async def list_unresolved(self) -> list[AwaitableTask]:
        async with self._pool.connection() as conn:
            row = await conn.execute(
                "SELECT task_id, execution_id, step_id, kind, provider, state, "
                "       provider_task_id, submission_receipt, completion_receipt, "
                "       submitted_at, completed_at, deadline, resume_payload, metadata, updated_at "
                "FROM awaitable_tasks WHERE state NOT IN (%s, %s, %s, %s)",
                (
                    AwaitableState.COMPLETED.value,
                    AwaitableState.FAILED.value,
                    AwaitableState.TIMED_OUT.value,
                    AwaitableState.CANCELLED.value,
                ),
            )
            rows = await row.fetchall()
            return [self._row_to_task(r) for r in rows]

    @staticmethod
    def _row_to_task(r: Any) -> AwaitableTask:
        return AwaitableTask(
            task_id=r[0],
            execution_id=r[1],
            step_id=r[2],
            kind=AwaitableKind(r[3]),
            provider=r[4],
            state=AwaitableState(r[5]),
            provider_task_id=r[6],
            submission_receipt=json.loads(r[7]) if r[7] else None,
            completion_receipt=json.loads(r[8]) if r[8] else None,
            submitted_at=r[9],
            completed_at=r[10],
            deadline=r[11],
            resume_payload=json.loads(r[12]) if r[12] else None,
            metadata=json.loads(r[13]) if r[13] else {},
            updated_at=r[14],
        )


__all__ = ["PgAwaitableTaskStore"]
