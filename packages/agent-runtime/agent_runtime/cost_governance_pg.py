"""PG 持久化 BudgetStore（V3 Phase 3）。

与 ``InMemoryBudgetStore`` 同接口，固定窗口分桶。
DDL 见 ``db.py`` 的 ``budget_usage`` / ``budget_limits`` 表。
"""

from __future__ import annotations

import time
from typing import Any

from agent_runtime.cost_governance import BudgetDimension, BudgetStore


class PgBudgetStore(BudgetStore):
    """PG 持久化预算存储（固定窗口分桶）。"""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    @staticmethod
    def _bucket_index(window_seconds: float) -> int:
        return int(time.time() // window_seconds)

    async def record(
        self, tenant_id: str, dimension: BudgetDimension, amount: float, window_seconds: float
    ) -> float:
        bucket = self._bucket_index(window_seconds)
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO budget_usage (tenant_id, dimension, bucket_index, used) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (tenant_id, dimension, bucket_index) DO UPDATE "
                "SET used = budget_usage.used + EXCLUDED.used, "
                "    updated_at = now()",
                (tenant_id, dimension.value, bucket, amount),
            )
            row = await conn.execute(
                "SELECT used FROM budget_usage "
                "WHERE tenant_id = %s AND dimension = %s AND bucket_index = %s",
                (tenant_id, dimension.value, bucket),
            )
            r = await row.fetchone()
            return r[0] if r else 0.0

    async def get_usage(
        self, tenant_id: str, dimension: BudgetDimension, window_seconds: float
    ) -> float:
        bucket = self._bucket_index(window_seconds)
        async with self._pool.connection() as conn:
            row = await conn.execute(
                "SELECT used FROM budget_usage "
                "WHERE tenant_id = %s AND dimension = %s AND bucket_index = %s",
                (tenant_id, dimension.value, bucket),
            )
            r = await row.fetchone()
            return r[0] if r else 0.0


__all__ = ["PgBudgetStore"]
