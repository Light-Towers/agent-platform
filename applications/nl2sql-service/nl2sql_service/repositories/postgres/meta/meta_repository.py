"""元知识库 Postgres 仓储：列/指标/值信息 CRUD（幂等 upsert，#107）。

写入侧一律 `ON CONFLICT <唯一约束> DO UPDATE`：DDL 的 uq_* 约束注释写明是
"P0-2 幂等重建的冲突目标"——裸 INSERT 会让同输入重跑第二次撞 UniqueViolation
中途回滚（M0-2"连跑两次完全一致"半交付）。
"""

from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)

#: 各表唯一约束（= ON CONFLICT 冲突目标；与 001_meta_schema.up.sql 的 uq_* 逐列一致）
_CONFLICT_TARGETS = {
    "column_info": ("tenant_id", "workspace_id", "datasource_id", "table_name", "column_name"),
    "metric_info": ("tenant_id", "workspace_id", "datasource_id", "metric_name"),
    "value_info": ("tenant_id", "workspace_id", "datasource_id", "column_name", "value"),
}


def _upsert_sql(prefix: str, table: str, data: dict[str, Any]) -> str:
    """按既有唯一约束拼幂等 upsert；入参键全部落在冲突目标上时退 DO NOTHING。"""
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["%s"] * len(data))
    conflict = _CONFLICT_TARGETS[table]
    conflict_cols = "(" + ", ".join(conflict) + ")"
    updatable = [k for k in data if k not in conflict]
    if updatable:
        action = "DO UPDATE SET " + ", ".join(f"{k} = EXCLUDED.{k}" for k in updatable)
    else:
        action = "DO NOTHING"
    return f"INSERT INTO {prefix}{table} ({cols}) VALUES ({placeholders}) ON CONFLICT {conflict_cols} {action}"


class MetaRepository:
    """元知识库仓储。"""

    def __init__(self, pool=None, table_prefix: str = "nl2sql_") -> None:
        self._pool = pool
        self._prefix = table_prefix

    async def save_column(self, data: dict[str, Any]) -> None:
        sql = _upsert_sql(self._prefix, "column_info", data)
        async with self._pool.connection() as conn:
            await conn.execute(sql, tuple(data.values()))

    async def save_metric(self, data: dict[str, Any]) -> None:
        sql = _upsert_sql(self._prefix, "metric_info", data)
        async with self._pool.connection() as conn:
            await conn.execute(sql, tuple(data.values()))

    async def save_value(self, data: dict[str, Any]) -> None:
        sql = _upsert_sql(self._prefix, "value_info", data)
        async with self._pool.connection() as conn:
            await conn.execute(sql, tuple(data.values()))

    async def list_metrics(self) -> list[dict[str, Any]]:
        sql = f"SELECT metric_name, metric_desc, metric_expr FROM {self._prefix}metric_info"
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql)
            rows = await cur.fetchall()
            return [dict(r._mapping) for r in rows]
