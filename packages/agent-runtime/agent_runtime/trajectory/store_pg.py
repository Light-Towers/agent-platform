"""PG Trajectory 存储后端（P3-1）。

提供 ``PgTrajectoryStore``：按 execution_id 持久化完整轨迹（含 steps / plan / snapshot / tokens / cost）。
遵循 §20 约束：PG = 事实源，LISTEN/NOTIFY 仅唤醒，periodic reconcile 兜底（trajectory 仅写入/查询，无跨进程唤醒需求）。
"""

from __future__ import annotations

import json
import time
from typing import Any

from agent_runtime.trajectory.models import TrajectoryRecord
from agent_runtime.trajectory.store import TrajectoryStore, _coerce_record


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _loads(val: Any) -> Any:
    if isinstance(val, str):
        return json.loads(val)
    return val


class PgTrajectoryStore(TrajectoryStore):
    """PG 轨迹存储：trajectories 表。

    字段：
    - execution_id PK
    - parent_execution_id
    - session_id
    - planner
    - plan JSONB
    - steps JSONB
    - total_tokens
    - total_cost
    - snapshot JSONB
    - created_at timestamptz
    """

    def __init__(self, pool: Any, *, table: str = "trajectories") -> None:
        self._pool = pool
        self._table = table

    async def save(self, record: TrajectoryRecord) -> None:
        sql = (
            f"INSERT INTO {self._table} "
            "(execution_id, parent_execution_id, session_id, planner, plan, steps, "
            " total_tokens, total_cost, snapshot, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now()) "
            "ON CONFLICT (execution_id) DO UPDATE "
            "SET parent_execution_id = EXCLUDED.parent_execution_id, "
            "    session_id = EXCLUDED.session_id, "
            "    planner = EXCLUDED.planner, "
            "    plan = EXCLUDED.plan, "
            "    steps = EXCLUDED.steps, "
            "    total_tokens = EXCLUDED.total_tokens, "
            "    total_cost = EXCLUDED.total_cost, "
            "    snapshot = EXCLUDED.snapshot, "
            "    created_at = now()"
        )
        steps_json = [s.to_dict() for s in record.steps]
        async with self._pool.connection() as conn:
            await conn.execute(
                sql,
                (
                    record.execution_id,
                    record.parent_execution_id,
                    record.session_id,
                    record.planner,
                    _dumps(record.plan),
                    _dumps(steps_json),
                    record.total_tokens,
                    record.total_cost,
                    _dumps(record.snapshot),
                ),
            )

    async def get(self, execution_id: str) -> TrajectoryRecord | None:
        sql = (
            f"SELECT execution_id, parent_execution_id, session_id, planner, plan, steps, "
            "       total_tokens, total_cost, snapshot, created_at "
            f"FROM {self._table} WHERE execution_id = %s"
        )
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql, (execution_id,))
            row = await cur.fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    async def list_by_session(self, session_id: str) -> list:
        sql = (
            f"SELECT execution_id, parent_execution_id, session_id, planner, plan, steps, "
            "       total_tokens, total_cost, snapshot, created_at "
            f"FROM {self._table} WHERE session_id = %s ORDER BY created_at DESC"
        )
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql, (session_id,))
            rows = await cur.fetchall()
        return [self._row_to_record(r) for r in rows]

    def _row_to_record(self, row) -> TrajectoryRecord:
        (
            execution_id,
            parent_execution_id,
            session_id,
            planner,
            plan_json,
            steps_json,
            total_tokens,
            total_cost,
            snapshot_json,
            created_at,
        ) = row
        return TrajectoryRecord(
            execution_id=execution_id,
            parent_execution_id=parent_execution_id,
            session_id=session_id,
            planner=planner,
            plan=_loads(plan_json) if plan_json else {},
            steps=_loads(steps_json) if steps_json else [],
            total_tokens=total_tokens or 0,
            total_cost=total_cost or 0.0,
            snapshot=_loads(snapshot_json) if snapshot_json else {},
            created_at=created_at.timestamp() if created_at else time.time(),
        )