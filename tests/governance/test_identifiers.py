# -*- coding: utf-8 -*-
"""标识符白名单用例（2026-10-18，P0-10 / S4 四处拼接点收敛）。

钉四件事：
1. `agent_core.sql.identifiers` 是单一正则来源，合法/非法边界正确；
2. nl2sql 的 pgvector 客户端拒绝非法表名/列名，且 filter 只能走结构化参数
   （`filter_clause` 整段 SQL 的能力已取消——那是 S4 登记的最高危拼接点）；
3. MetaRepository 构造期拒绝非法表前缀（配置也是外部输入）；
4. agent-core 的 `PgVectorMemoryBackend` 构造期拒绝非法表名（S4 第四处）。
"""

from __future__ import annotations

import pytest
from agent_core.memory.vector_backend import PgVectorMemoryBackend
from agent_core.sql.identifiers import (
    validate_identifier,
    validate_identifier_list,
    validate_prefixed_table,
)
from nl2sql_service.clients.pgvector_client_manager import PgvectorClientManager
from nl2sql_service.repositories.postgres.meta.meta_repository import MetaRepository


def test_identifier_boundaries():
    for ok in ("orders", "_tmp", "a1_b2", "nl2sql_column_info"):
        assert validate_identifier(ok) == ok
    for bad in ("", "orders;drop", "orders--x", "Order", "orders.x", "orders x", "1abc", "订单表"):
        with pytest.raises(ValueError, match="非法标识符"):
            validate_identifier(bad, "测试")


def test_identifier_list_rejects_empty_and_bad_items():
    assert validate_identifier_list("a, b ,c") == ["a", "b", "c"]
    for bad in ("a,,b", "a, ;drop", ""):
        with pytest.raises(ValueError):
            validate_identifier_list(bad, "列清单")


def test_prefixed_table_validates_both_segments():
    assert validate_prefixed_table("nl2sql_column_info", "nl2sql_") == "nl2sql_column_info"
    with pytest.raises(ValueError, match="表前缀"):
        validate_prefixed_table("nl2sql_column_info", "nl2sql;drop")
    with pytest.raises(ValueError, match="表名"):
        validate_prefixed_table("nl2sql_column info", "nl2sql_")


async def test_pgvector_client_rejects_illegal_identifiers():
    client = PgvectorClientManager(pool=None)
    for kwargs in (
        {"table": "nl2sql_column_info; drop", "embedding_col": "embedding", "query_embedding": [0.1]},
        {"table": "nl2sql_column_info", "embedding_col": "embedding; --", "query_embedding": [0.1]},
        {"table": "nl2sql_column_info", "embedding_col": "embedding", "query_embedding": [0.1], "extra_cols": "a, ;drop"},
    ):
        with pytest.raises(ValueError, match="非法标识符"):
            await client.vector_search(top_k=5, **kwargs)


async def test_pgvector_client_filters_are_structured_and_parameterized():
    """结构化 filter：列名过白名单、值进参数，调用方没有传 SQL 片段的能力。"""
    recorded: dict = {}

    class _Cursor:
        async def fetchall(self):
            return []

    class _Conn:
        async def execute(self, sql, params):
            recorded["sql"] = sql
            recorded["params"] = params
            return _Cursor()

    class _ConnCtx:
        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, *exc):
            return False

    class _Pool:
        def connection(self):
            return _ConnCtx()

    client = PgvectorClientManager(pool=_Pool())
    await client.vector_search(
        table="nl2sql_column_info",
        embedding_col="embedding",
        query_embedding=[0.1, 0.2],
        top_k=3,
        extra_cols="table_name",
        filters=(("datasource_id", "ds-1"), ("tenant_id", "t-1")),
    )
    assert "WHERE datasource_id = %s AND tenant_id = %s" in recorded["sql"]
    assert recorded["params"] == ("ds-1", "t-1", [0.1, 0.2], 3)


async def test_fulltext_search_rejects_illegal_tsvector_column():
    client = PgvectorClientManager(pool=None)
    with pytest.raises(ValueError, match="非法标识符"):
        await client.fulltext_search("nl2sql_value_info", "value_tsvector; drop", ["销售"])


def test_meta_repository_rejects_illegal_prefix():
    with pytest.raises(ValueError, match="元知识表前缀"):
        MetaRepository(pool=None, table_prefix="nl2sql; drop")


def test_memory_backend_rejects_illegal_collection():
    with pytest.raises(ValueError, match="记忆表名"):
        PgVectorMemoryBackend(database_url="postgresql://x", collection="memories; drop")
