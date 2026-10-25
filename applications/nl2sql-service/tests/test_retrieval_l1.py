# -*- coding: utf-8 -*-
"""取值路退役与相对截断用例（2026-10-18，P0-5①④ / §5.3 落位表）。

钉四件事：
1. 取值召回改**码表字面检索**（大小写不敏感等值 + 前缀）——不再走 ANN、
   不再走中文全文模糊（B1 已证 simple 词典对中文整串当词，实际不可用）；
2. 自由文本型取值的模糊匹配不在 PG 做（改由 P0-9 只读探针在源侧完成），
   `embedding` 形参保留但召回路不再消费；
3. 列/指标向量召回支持**相对截断**（与最佳分差超过 margin 即丢，
   绝对分跨查询不可比）；margin<=0 关闭；
4. 结构化 filters 贯通三路（datasource_id 作用域，N3 缺口的补齐）。
"""

from __future__ import annotations

from nl2sql_service.clients.pgvector_client_manager import PgvectorClientManager, relative_truncate
from nl2sql_service.repositories.pgvector.column_repository import ColumnRepository
from nl2sql_service.repositories.pgvector.metric_repository import MetricRepository
from nl2sql_service.repositories.pgvector.value_repository import ValueRepository


class _Cursor:
    """psycopg 行替身：连接配 row_factory=dict_row，fetchall() 直接返回 dict。"""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = [dict(r) for r in rows]

    async def fetchall(self) -> list[dict]:
        return self._rows


class _Conn:
    def __init__(self, pool: "_Pool") -> None:
        self._pool = pool

    async def execute(self, sql: str, params: tuple) -> _Cursor:
        self._pool.last = (sql, params)
        return _Cursor(self._pool.rows)


class _ConnCtx:
    def __init__(self, pool: "_Pool") -> None:
        self._pool = pool

    async def __aenter__(self) -> _Conn:
        return _Conn(self._pool)

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _Pool:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows or []
        self.last: tuple[str, tuple] | None = None

    def connection(self) -> _ConnCtx:
        return _ConnCtx(self)


# ---------------------------------------------------------------------------
# 相对截断
# ---------------------------------------------------------------------------
def test_relative_truncate_cuts_by_margin():
    rows = [{"v": "a", "distance": 0.10}, {"v": "b", "distance": 0.18}, {"v": "c", "distance": 0.60}]
    assert [r["v"] for r in relative_truncate(rows, 0.15)] == ["a", "b"]
    assert [r["v"] for r in relative_truncate(rows, 0.0)] == ["a", "b", "c"], "margin<=0 关闭截断"
    assert relative_truncate([], 0.15) == []


# ---------------------------------------------------------------------------
# 取值：码表字面路
# ---------------------------------------------------------------------------
async def test_value_recall_uses_literal_search_not_ann():
    pool = _Pool([{"table_name": "orders", "column_name": "order_status", "value": "已支付", "value_desc": ""}])
    repo = ValueRepository(PgvectorClientManager(pool=pool))

    rows = await repo.recall(["已支", "VIP"], embedding=[0.1, 0.2], top_k=5)

    assert rows == [{"table_name": "orders", "column_name": "order_status", "value": "已支付", "value_desc": ""}]
    sql, params = pool.last or ("", ())
    assert "<=>" not in sql, "取值召回不得走 ANN（P0-5① 退役）"
    assert "value_tsvector" not in sql, "取值召回不得走中文全文模糊（B1 已证不可用）"
    assert "LIKE ANY" in sql and "= ANY" in sql, "必须是等值 + 前缀字面检索"
    assert params == (["已支", "vip"], ["已支%", "VIP%"], 5), f"参数形状漂移: {params}"


async def test_value_recall_empty_keywords_skips_db():
    pool = _Pool()
    repo = ValueRepository(PgvectorClientManager(pool=pool))
    assert await repo.recall([], embedding=[0.1]) == []
    assert pool.last is None, "空关键词不许碰库"


async def test_value_recall_passes_datasource_filter():
    pool = _Pool()
    repo = ValueRepository(PgvectorClientManager(pool=pool))
    await repo.recall(["VIP"], filters=(("datasource_id", "ds-1"),))
    sql, params = pool.last or ("", ())
    assert "datasource_id = %s" in sql
    assert params == ("ds-1", ["vip"], ["VIP%"], 10)


# ---------------------------------------------------------------------------
# 列/指标：向量路 + 相对截断
# ---------------------------------------------------------------------------
async def test_column_recall_applies_relative_truncate():
    pool = _Pool(
        [
            {"column_name": "amount", "distance": 0.10},
            {"column_name": "note", "distance": 0.80},
        ]
    )
    repo = ColumnRepository(PgvectorClientManager(pool=pool))

    rows = await repo.recall(["金额"], embedding=[0.1], top_k=10, score_margin=0.15)

    assert [r["column_name"] for r in rows] == ["amount"], "margin 外的弱匹配必须截掉"


async def test_metric_recall_zero_margin_keeps_topk():
    pool = _Pool([{"metric_name": "a", "distance": 0.10}, {"metric_name": "b", "distance": 0.80}])
    repo = MetricRepository(PgvectorClientManager(pool=pool))

    rows = await repo.recall(["x"], embedding=[0.1], top_k=10, score_margin=0.0)

    assert [r["metric_name"] for r in rows] == ["a", "b"]


async def test_vector_recall_still_requires_embedding():
    pool = _Pool([{"column_name": "amount", "distance": 0.1}])
    repo = ColumnRepository(PgvectorClientManager(pool=pool))
    assert await repo.recall(["金额"], embedding=None) == []
    assert pool.last is None
