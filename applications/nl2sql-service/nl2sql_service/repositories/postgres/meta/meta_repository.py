"""元知识库 Postgres 仓储：列/指标/值信息 upsert + 差异删除。

2026-10-18（方案 P0-1 / P0-2 实装）：此前三个 `save_*` 用 `data.keys()`
动态拼列名 + 纯 INSERT——一是指名注入面（P0-10：data 来自 YAML/DDL 派生
文本），二是"重跑一次多一整套副本、被删的取值永远留在索引里"（H3）。
现按 `migrations/001_meta_schema.up.sql` 的唯一键**写死列清单 + 参数化
upsert**；`prune_*` 删掉源里已不存在的行（差异重建的另一半）。

注意 001 是唯一真相源：这里每个表的列清单/冲突键必须与它逐字对齐，
改 schema 时两处一起改（新增 002_*.up.sql，不回改 001）。
"""

from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)

#: 三个作用域列是 P1-1 / P1-6 的前置槽位：当前无写入方，DDL 默认 ''。
#: upsert 与 prune 必须与之一致——ON CONFLICT 打不中、prune 扫不到行，
#: 都是"看着跑了其实没生效"的暗断点。
_SCOPE_COLS = ("tenant_id", "workspace_id", "datasource_id")

#: 各表（相对 table_prefix 的表名, 唯一键即 001 的 CONSTRAINT uq_*, 可更新列）。
#: 列清单写死：值全部参数化，SQL 标识符只来自本模块常量。
_COLUMN_TABLE = ("column_info", ("tenant_id", "workspace_id", "datasource_id", "table_name", "column_name"), ("table_comment", "column_comment", "data_type", "embedding"))
_METRIC_TABLE = ("metric_info", ("tenant_id", "workspace_id", "datasource_id", "metric_name"), ("metric_desc", "metric_expr", "embedding"))
_VALUE_TABLE = ("value_info", ("tenant_id", "workspace_id", "datasource_id", "column_name", "value"), ("value_desc", "search_text", "embedding"))

#: 各表的自然键（= 唯一键去掉作用域列）：prune 的 NOT IN 比较目标。
_COLUMN_NATURAL = ("table_name", "column_name")
_METRIC_NATURAL = ("metric_name",)
_VALUE_NATURAL = ("column_name", "value")


class MetaRepository:
    """元知识库仓储（幂等写入 + 作用域内差异删除）。"""

    def __init__(self, pool=None, table_prefix: str = "nl2sql_") -> None:
        self._pool = pool
        self._prefix = table_prefix

    async def save_column(self, data: dict[str, Any]) -> bool:
        """列行 upsert；返回 True=新插入 / False=更新了已存在行。"""
        return await self._upsert(_COLUMN_TABLE, data)

    async def save_metric(self, data: dict[str, Any]) -> bool:
        """指标行 upsert；返回 True=新插入 / False=更新了已存在行。"""
        return await self._upsert(_METRIC_TABLE, data)

    async def save_value(self, data: dict[str, Any]) -> bool:
        """取值行 upsert（search_text 必须由构建方写入，见模块 docstring）；返回插入/更新。"""
        return await self._upsert(_VALUE_TABLE, data)

    async def prune_columns(self, keep: set[tuple[str, str]]) -> int:
        """删除作用域内不在 keep 的列行（keep = {(table_name, column_name)}）。"""
        return await self._prune(_COLUMN_TABLE[0], _COLUMN_NATURAL, keep)

    async def prune_metrics(self, keep: set[str]) -> int:
        """删除作用域内不在 keep 的指标行（keep = {metric_name}）。

        str 必须包成 1-tuples 再下传：`_prune` 按"每个 key 展平成一个 VALUES 行"
        取参，直接传字符串会被逐字符拆开（fake 池与真 PG 都会在这里炸）。
        """
        return await self._prune(_METRIC_TABLE[0], _METRIC_NATURAL, {(name,) for name in keep})

    async def prune_values(self, keep: set[tuple[str, str]]) -> int:
        """删除作用域内不在 keep 的取值行（keep = {(column_name, value)}）。"""
        return await self._prune(_VALUE_TABLE[0], _VALUE_NATURAL, keep)

    async def list_metrics(self) -> list[dict[str, Any]]:
        sql = f"SELECT metric_name, metric_desc, metric_expr FROM {self._prefix}metric_info"
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql)
            rows = await cur.fetchall()
            return [dict(r._mapping) for r in rows]

    async def _upsert(
        self,
        table_spec: tuple[str, tuple[str, ...], tuple[str, ...]],
        data: dict[str, Any],
    ) -> bool:
        """按写死列清单 upsert，返回 True=插入（PG 惯例 `xmax = 0` 判新行）。

        禁 `data.keys()` 动态列名：列清单来自常量，入参只做值——构建入口的
        注释/表达式是自由文本，不能进 SQL 标识符位。
        """
        table, key_cols, updatable = table_spec
        insert_cols = list(key_cols) + [c for c in updatable if c not in key_cols]
        row = {c: "" for c in _SCOPE_COLS}
        row.update(data)
        params = tuple(row.get(c) for c in insert_cols)
        sql = (
            f"INSERT INTO {self._prefix}{table} ({', '.join(insert_cols)}) "
            f"VALUES ({', '.join(['%s'] * len(insert_cols))}) "
            f"ON CONFLICT ({', '.join(key_cols)}) DO UPDATE SET "
            + ", ".join(f"{c} = EXCLUDED.{c}" for c in updatable)
            + ", updated_at = now() RETURNING (xmax = 0) AS inserted"
        )
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql, params)
            row = await cur.fetchone()
        return bool(row[0]) if row is not None else False

    async def _prune(self, table: str, natural_cols: tuple[str, ...], keep: set[tuple[str, ...]]) -> int:
        """删除作用域内自然键不在 keep 的行；keep 为空 = 清空作用域（源已为空）。"""
        scope_params = tuple("" for _ in _SCOPE_COLS)
        scope_sql = " AND ".join(f"{c} = %s" for c in _SCOPE_COLS)
        if not keep:
            sql = f"DELETE FROM {self._prefix}{table} WHERE {scope_sql}"
            params = scope_params
        else:
            # 行值 NOT IN (VALUES ...)：自然键整体比较，避免逐列 OR 的优先级坑
            row_tpl = "(" + ", ".join(["%s"] * len(natural_cols)) + ")"
            values_sql = ", ".join([row_tpl] * len(keep))
            sql = (
                f"DELETE FROM {self._prefix}{table} WHERE {scope_sql} "
                f"AND ({', '.join(natural_cols)}) NOT IN (VALUES {values_sql})"
            )
            params = scope_params + tuple(v for key in keep for v in key)
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql, params)
            return cur.rowcount or 0
