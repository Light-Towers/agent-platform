"""漂移检测（P0-3）：比对源 schema 与元知识库，输出三类差异。

设计纪律（方案 P0-3 行）：
- **差异默认报警不自动改语义**——只有类型与样本自动跟（`apply_type_updates`
  只写 `data_type`）；新增/删除列只报告，人工决定是否进语义层。
- 表统计（行数估值）是**副产物**：驱动生成期聚合引导（§5.11-V3-3），
  估值是估算值（`reltuples`/`TABLE_ROWS`），引导用不着精确 count。
- 按源分支两套 SQL（§5.6 落位表）：`information_schema.columns` 两侧通用，
  行数估值按方言分（PG 走 `pg_class`，MySQL 走 `information_schema.tables`，
  未知方言不估——不猜）。

这不是定时任务：触发方式（cron / 同步下游钩子 / 手动 CLI）随 H2 登记，
本模块只提供"检测"这一件事的确定实现。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)

#: information_schema.columns 取列指纹（PG/MySQL 同视图；Doris 亦兼容）
_SOURCE_COLUMNS_SQL = (
    "SELECT table_name, column_name, data_type, ordinal_position "
    "FROM information_schema.columns "
    "WHERE table_schema = %s "
    "ORDER BY table_name, ordinal_position"
)
#: 行数估值：PG 用 pg_class.reltuples（估算，免 count）
_PG_TABLE_STATS_SQL = (
    "SELECT relname AS table_name, reltuples::bigint AS row_estimate "
    "FROM pg_class WHERE relkind IN ('r', 'p') AND relnamespace = 'public'::regnamespace"
)
#: 行数估值：MySQL 用 information_schema.tables.TABLE_ROWS（同为估算）
_MYSQL_TABLE_STATS_SQL = (
    "SELECT table_name, table_rows AS row_estimate "
    "FROM information_schema.tables WHERE table_schema = %s AND table_type = 'BASE TABLE'"
)


@dataclass(frozen=True)
class ColumnKey:
    table_name: str
    column_name: str


@dataclass
class DriftReport:
    """三类差异 + 未变列数 + 表统计。`to_dict()` 供 CLI/JSON 输出。"""

    added: list[dict[str, Any]] = field(default_factory=list)
    deleted: list[dict[str, Any]] = field(default_factory=list)
    type_changed: list[dict[str, Any]] = field(default_factory=list)
    unchanged: int = 0
    table_stats: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return bool(self.added or self.deleted or self.type_changed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "added": self.added,
            "deleted": self.deleted,
            "type_changed": self.type_changed,
            "unchanged": self.unchanged,
            "table_stats": self.table_stats,
        }


class DriftDetector:
    """源 schema vs 元知识库 的差异检测器。"""

    def __init__(
        self,
        dw_repository: Any,
        meta_repository: Any,
        dialect: str = "postgres",
        schema: str = "public",
        datasource_id: str = "",
    ) -> None:
        self._dw = dw_repository
        self._meta = meta_repository
        self._dialect = dialect
        self._schema = schema
        self._datasource_id = datasource_id

    async def collect_source(self) -> list[dict[str, Any]]:
        return await self._dw.execute_readonly(_SOURCE_COLUMNS_SQL, (self._schema,))

    async def collect_meta(self) -> list[dict[str, Any]]:
        return await self._meta.list_columns(self._datasource_id)

    async def collect_table_stats(self) -> list[dict[str, Any]]:
        """行数估值按方言分支；未知方言返回空（不猜表大小）。"""
        if self._dialect == "postgres":
            rows = await self._dw.execute_readonly(_PG_TABLE_STATS_SQL)
            return [
                {
                    "table_name": r["table_name"],
                    "row_estimate": int(r.get("row_estimate") or 0),
                    "datasource_id": self._datasource_id,
                }
                for r in rows
            ]
        if self._dialect == "mysql":
            rows = await self._dw.execute_readonly(_MYSQL_TABLE_STATS_SQL, (self._schema,))
            return [
                {
                    "table_name": r["table_name"],
                    "row_estimate": int(r.get("row_estimate") or 0),
                    "datasource_id": self._datasource_id,
                }
                for r in rows
            ]
        logger.info("dialect=%s 无行数估值口径，跳过表统计", self._dialect)
        return []

    @staticmethod
    def diff(source: list[dict[str, Any]], meta: list[dict[str, Any]]) -> DriftReport:
        """纯函数 diff：新增（源有库无）/ 删除（库有源无）/ 类型变更。"""
        source_map = {
            ColumnKey(r["table_name"], r["column_name"]): r for r in source
        }
        meta_map = {ColumnKey(r["table_name"], r["column_name"]): r for r in meta}
        report = DriftReport()
        for key, row in source_map.items():
            if key not in meta_map:
                report.added.append(dict(row))
            elif (meta_map[key].get("data_type") or "") != (row.get("data_type") or ""):
                report.type_changed.append(
                    {
                        "table_name": key.table_name,
                        "column_name": key.column_name,
                        "old_type": meta_map[key].get("data_type") or "",
                        "new_type": row.get("data_type") or "",
                    }
                )
            else:
                report.unchanged += 1
        for key, row in meta_map.items():
            if key not in source_map:
                report.deleted.append(dict(row))
        return report

    async def detect(self, with_stats: bool = True) -> DriftReport:
        report = self.diff(await self.collect_source(), await self.collect_meta())
        if with_stats:
            report.table_stats = await self.collect_table_stats()
        if report.has_drift:
            logger.warning(
                "schema drift: +%d -%d ~%d（报警不自动改语义，类型除外）",
                len(report.added),
                len(report.deleted),
                len(report.type_changed),
            )
        return report

    async def apply_type_updates(self, report: DriftReport) -> int:
        """只跟类型（P0-3 的唯一自动写）；新增/删除列不自动进语义层。"""
        applied = 0
        for change in report.type_changed:
            await self._meta.update_column_type(
                change["table_name"], change["column_name"], change["new_type"]
            )
            applied += 1
        return applied

    async def refresh_table_stats(self, report: DriftReport) -> int:
        return await self._meta.upsert_table_stats(report.table_stats)
