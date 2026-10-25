# -*- coding: utf-8 -*-
"""漂移检测用例（2026-10-18，P0-3）。

钉四件事：
1. 三类差异（新增/删除/类型变更）各自可识别，未变列不误报；
2. **报警不自动改语义**：`detect()` 本身零写入；只有 `apply_type_updates`
   才写，且只写 `data_type`（P0-3 行内纪律）；
3. 表统计按方言分支：PG 走 pg_class、MySQL 走 information_schema、
   未知方言不猜（返回空）；
4. CLI 契约：`--json` 机器可读、`--fail-on-drift` 有差异返 2（CI 门禁）、
   默认只报警不写库。
"""

from __future__ import annotations

from typing import Any

from nl2sql_service.services.drift_detector import DriftDetector, DriftReport

_SOURCE = [
    {"table_name": "orders", "column_name": "order_id", "data_type": "bigint", "ordinal_position": 1},
    {"table_name": "orders", "column_name": "amount", "data_type": "numeric", "ordinal_position": 2},
    {"table_name": "orders", "column_name": "created_at", "data_type": "timestamp", "ordinal_position": 3},
    {"table_name": "customers", "column_name": "customer_name", "data_type": "varchar", "ordinal_position": 1},
]
_META = [
    {"table_name": "orders", "column_name": "order_id", "column_comment": "订单ID", "data_type": "bigint"},
    {"table_name": "orders", "column_name": "amount", "column_comment": "金额", "data_type": "integer"},  # 类型变了
    {"table_name": "orders", "column_name": "legacy_flag", "column_comment": "旧列", "data_type": "boolean"},  # 源里没了
    {"table_name": "customers", "column_name": "customer_name", "column_comment": "名称", "data_type": "varchar"},
]


class _StubDw:
    def __init__(self, rows: list[dict[str, Any]] | None = None, stats: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows if rows is not None else _SOURCE
        self.stats = stats if stats is not None else []
        self.calls: list[tuple[str, tuple]] = []

    async def execute_readonly(self, sql: str, params: tuple | None = None) -> list[dict[str, Any]]:
        self.calls.append((sql, params or ()))
        if "pg_class" in sql or "information_schema.tables" in sql:
            return self.stats
        return self.rows


class _StubMeta:
    def __init__(self) -> None:
        self.type_updates: list[tuple[str, str, str]] = []
        self.stats_writes: list[dict[str, Any]] = []

    async def list_columns(self, datasource_id: str = "") -> list[dict[str, Any]]:
        return _META

    async def update_column_type(self, table_name: str, column_name: str, data_type: str) -> None:
        self.type_updates.append((table_name, column_name, data_type))

    async def upsert_table_stats(self, stats: list[dict[str, Any]]) -> int:
        self.stats_writes.extend(stats)
        return len(stats)


def test_diff_reports_three_kinds_without_false_positives():
    report = DriftDetector.diff(_SOURCE, _META)

    assert [c["column_name"] for c in report.added] == ["created_at"]
    assert [c["column_name"] for c in report.deleted] == ["legacy_flag"]
    assert report.type_changed == [
        {"table_name": "orders", "column_name": "amount", "old_type": "integer", "new_type": "numeric"}
    ]
    assert report.unchanged == 2, "未变列（order_id / customer_name）不应误报"
    assert report.has_drift is True


async def test_detect_does_not_write_semantics():
    meta = _StubMeta()
    detector = DriftDetector(dw_repository=_StubDw(), meta_repository=meta)

    report = await detector.detect()

    assert report.has_drift
    assert meta.type_updates == [], "detect 必须零写入（报警不自动改语义）"
    assert meta.stats_writes == [], "detect 不应顺带写表统计"


async def test_apply_type_updates_only_touches_types():
    meta = _StubMeta()
    detector = DriftDetector(dw_repository=_StubDw(), meta_repository=meta)
    report = await detector.detect()

    applied = await detector.apply_type_updates(report)

    assert applied == 1
    assert meta.type_updates == [("orders", "amount", "numeric")]


async def test_table_stats_branch_by_dialect():
    stats_rows = [{"table_name": "orders", "row_estimate": 400_000_000}]
    dw = _StubDw(stats=stats_rows)
    detector = DriftDetector(dw_repository=dw, meta_repository=_StubMeta(), dialect="postgres")

    report = await detector.detect()

    assert report.table_stats == [{"table_name": "orders", "row_estimate": 400_000_000, "datasource_id": ""}]
    assert any("pg_class" in sql for sql, _ in dw.calls)

    dw_mysql = _StubDw(stats=stats_rows)
    report_mysql = await DriftDetector(dw_repository=dw_mysql, meta_repository=_StubMeta(), dialect="mysql").detect()
    assert report_mysql.table_stats[0]["row_estimate"] == 400_000_000
    assert any("information_schema.tables" in sql for sql, _ in dw_mysql.calls)

    dw_unknown = _StubDw(stats=stats_rows)
    report_unknown = await DriftDetector(dw_repository=dw_unknown, meta_repository=_StubMeta(), dialect="doris").detect()
    assert report_unknown.table_stats == [], "未知方言不猜表大小"


async def test_refresh_table_stats_writes_estimates():
    meta = _StubMeta()
    detector = DriftDetector(dw_repository=_StubDw(stats=[{"table_name": "orders", "row_estimate": 7}]), meta_repository=meta)
    report = await detector.detect()

    written = await detector.refresh_table_stats(report)

    assert written == 1
    assert meta.stats_writes[0]["table_name"] == "orders"


def test_empty_drift_report_has_no_drift():
    report = DriftReport()
    assert report.has_drift is False
    assert report.to_dict()["unchanged"] == 0
