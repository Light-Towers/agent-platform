# -*- coding: utf-8 -*-
"""agent_server/sql → nl2sql 迁移用例（A 方案 Stage ②，2026-10-18）。

钉八件事：
1. 三表按 (tenant, workspace) 分 scope，源作用域保真（不覆盖时）；
2. docs 只关联**同作用域**的表（跨租户文档串味 = 隔离破裂）；
3. table_comment 合并 COMMENT ON + 关联文档（后者追加，不覆盖前者）；
4. 空 question 的范例记账跳过（自然键不能空——否则互相覆盖）；
5. 未命中表名的文档 / 解析失败的 DDL 进记账列表，绝不静默；
6. --tenant/--workspace 是覆盖（单租户 legacy 库折叠）；
7. _embed_batched 分片保序；embedder=None 返回空向量（dry-run 路径）；
8. prune_examples 按作用域删（此前 _prune 硬编码 ''——scoped prune 静默空转）。
"""

from __future__ import annotations

from typing import Any

import pytest
from nl2sql_service.scripts.migrate_agent_server_sql import (
    _embed_batched,
    _read_source,
    build_migration_plan,
)
from nl2sql_service.repositories.postgres.meta.meta_repository import MetaRepository

_DDL = "CREATE TABLE orders (id BIGINT, amount NUMERIC(10,2)); COMMENT ON TABLE orders IS '订单主表';"
_DDL_BAD = "CREATE TABEL oops ("
_EXAMPLE = {"question": "上个月销售额", "sql": "SELECT SUM(amount) FROM orders"}


def _rows(tenant: str = "default", workspace: str = "", **over: Any) -> list[dict[str, Any]]:
    base = {"tenant_id": tenant, "workspace_id": workspace}
    return [{**base, **v} for v in over.get("items", [])]


# ---------------------------------------------------------------------------
# ① 计划：分 scope + 保真 + 合并
# ---------------------------------------------------------------------------
def test_plan_groups_by_scope_and_preserves_source_scope():
    plan = build_migration_plan(
        ddl_rows=[{"tenant_id": "default", "workspace_id": "", "content": _DDL}],
        doc_rows=[],
        example_rows=[{"tenant_id": "default", "workspace_id": "", **_EXAMPLE}],
    )
    assert len(plan["scopes"]) == 1
    scope = plan["scopes"][0]
    assert (scope["tenant_id"], scope["workspace_id"]) == ("default", ""), "源作用域保真（不默认折叠成 ''）"
    assert scope["tables"][0]["table_comment"] == "订单主表"
    assert [c["column_name"] for c in scope["tables"][0]["columns"]] == ["id", "amount"]
    assert scope["examples"] == [{**_EXAMPLE, "source": "human"}]


def test_plan_separates_tenants():
    plan = build_migration_plan(
        ddl_rows=[
            {"tenant_id": "t1", "workspace_id": "", "content": _DDL},
            {"tenant_id": "t2", "workspace_id": "", "content": "CREATE TABLE t2_only (id BIGINT);"},
        ],
        doc_rows=[{"tenant_id": "t1", "workspace_id": "", "content": "orders 的说明"}],
        example_rows=[{"tenant_id": "t2", "workspace_id": "", **_EXAMPLE}],
    )
    by_tenant = {s["tenant_id"]: s for s in plan["scopes"]}
    assert set(by_tenant) == {"t1", "t2"}
    assert [t["table_name"] for t in by_tenant["t1"]["tables"]] == ["orders"]
    assert [t["table_name"] for t in by_tenant["t2"]["tables"]] == ["t2_only"]
    assert by_tenant["t1"]["tables"][0]["table_comment"].endswith("orders 的说明")


# ---------------------------------------------------------------------------
# ② 文档只挂同作用域 + ③ 合并顺序
# ---------------------------------------------------------------------------
def test_docs_do_not_cross_tenant_boundary():
    plan = build_migration_plan(
        ddl_rows=[
            {"tenant_id": "t1", "workspace_id": "", "content": "CREATE TABLE orders (id BIGINT);"},
            {"tenant_id": "t2", "workspace_id": "", "content": "CREATE TABLE orders (id BIGINT);"},
        ],
        doc_rows=[{"tenant_id": "t1", "workspace_id": "", "content": "orders 只属于 t1 的口径"}],
        example_rows=[],
    )
    by_tenant = {s["tenant_id"]: s for s in plan["scopes"]}
    assert "只属于 t1 的口径" in by_tenant["t1"]["tables"][0]["table_comment"]
    assert by_tenant["t2"]["tables"][0]["table_comment"] == "", "t1 的文档不得串到 t2 的表注释"


def test_table_comment_appends_doc_after_comment_on():
    plan = build_migration_plan(
        ddl_rows=[{"tenant_id": "default", "workspace_id": "", "content": _DDL}],
        doc_rows=[{"tenant_id": "default", "workspace_id": "", "content": "orders 补充口径"}],
        example_rows=[],
    )
    comment = plan["scopes"][0]["tables"][0]["table_comment"]
    assert comment == "订单主表\n\norders 补充口径", "文档追加在 COMMENT ON 之后，不覆盖"


# ---------------------------------------------------------------------------
# ④ ⑤ 记账：空 question / 未命中文档 / 坏 DDL
# ---------------------------------------------------------------------------
def test_empty_question_examples_are_skipped_with_record():
    plan = build_migration_plan(
        ddl_rows=[],
        doc_rows=[],
        example_rows=[
            {"tenant_id": "default", "workspace_id": "", **_EXAMPLE},
            {"tenant_id": "default", "workspace_id": "", "question": "   ", "sql": "SELECT 1"},
        ],
    )
    assert plan["scopes"][0]["examples"] == [{**_EXAMPLE, "source": "human"}]
    assert plan["skipped_examples"] and "empty question" in plan["skipped_examples"][0]


def test_unmapped_docs_and_bad_ddl_are_recorded():
    plan = build_migration_plan(
        ddl_rows=[{"tenant_id": "default", "workspace_id": "", "content": _DDL_BAD}],
        doc_rows=[{"tenant_id": "default", "workspace_id": "", "content": "完全不提任何表名的运维手册"}],
        example_rows=[],
    )
    assert plan["skipped_ddl"] and "unparsed statement" in plan["skipped_ddl"][0]
    assert plan["unmapped_docs"] and "运维手册" in plan["unmapped_docs"][0]


# ---------------------------------------------------------------------------
# ⑥ 覆盖：单租户 legacy 折叠
# ---------------------------------------------------------------------------
def test_tenant_workspace_override_folds_legacy_rows():
    plan = build_migration_plan(
        ddl_rows=[{"tenant_id": "default", "workspace_id": "ws-a", "content": _DDL}],
        doc_rows=[],
        example_rows=[{"tenant_id": "default", "workspace_id": "ws-a", **_EXAMPLE}],
        tenant_override="",
        workspace_override="",
    )
    assert plan["scopes"][0]["tenant_id"] == "default"

    folded = build_migration_plan(
        ddl_rows=[{"tenant_id": "default", "workspace_id": "ws-a", "content": _DDL}],
        doc_rows=[],
        example_rows=[{"tenant_id": "default", "workspace_id": "ws-a", **_EXAMPLE}],
        tenant_override="t-new",
        workspace_override="w-new",
    )
    scope = folded["scopes"][0]
    assert (scope["tenant_id"], scope["workspace_id"]) == ("t-new", "w-new")


# ---------------------------------------------------------------------------
# ⑦ 批量向量化：分片保序
# ---------------------------------------------------------------------------
class _ChunkEmbedder:
    def __init__(self, dim: int = 4) -> None:
        self.dim = dim
        self.batches: list[list[str]] = []

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.batches.append(list(texts))
        return [[float(len(t))] * self.dim for t in texts]


async def test_embed_batched_chunks_and_preserves_order():
    embedder = _ChunkEmbedder()
    vectors = await _embed_batched(embedder, ["a", "bb", "ccc"], chunk=2)
    assert embedder.batches == [["a", "bb"], ["ccc"]], "按 chunk 分片"
    assert vectors == [[1.0] * 4, [2.0] * 4, [3.0] * 4], "保序对应"


async def test_embed_batched_none_embedder_returns_empty_vectors():
    assert await _embed_batched(None, ["a", "b"]) == [[], []]


# ---------------------------------------------------------------------------
# ⑧ prune 按作用域（_prune 此前硬编码 ''）
# ---------------------------------------------------------------------------
class _FakeCursor:
    def __init__(self, rowcount: int = 0) -> None:
        self.rowcount = rowcount


class _FakeConn:
    def __init__(self, pool: "_ScopePool") -> None:
        self._pool = pool

    async def execute(self, sql: str, params: tuple | None = None) -> _FakeCursor:
        self._pool.history.append((" ".join(sql.split()), tuple(params or ())))
        return _FakeCursor(rowcount=1)

    async def __aenter__(self) -> "_FakeConn":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _ScopePool:
    """记录 DELETE 的 SQL 与前三个参数（作用域）。"""

    def __init__(self) -> None:
        self.history: list[tuple[str, tuple]] = []

    def connection(self, *_a: Any, **_k: Any) -> _FakeConn:
        return _FakeConn(self)


async def test_prune_examples_uses_given_scope():
    pool = _ScopePool()
    repo = MetaRepository(pool=pool)
    await repo.prune_examples({"q1"}, tenant_id="t1", workspace_id="w1", datasource_id="ds1")
    sql, params = pool.history[-1]
    assert params[:3] == ("t1", "w1", "ds1"), f"prune 必须按调用方作用域删，实际 {params[:3]}"
    assert "nl2sql_example_info" in sql and "NOT IN" in sql


async def test_prune_defaults_to_empty_scope():
    """老调用方（不带 scope）行为不变：'' 作用域。"""
    pool = _ScopePool()
    await MetaRepository(pool=pool).prune_examples({"q1"})
    _sql, params = pool.history[-1]
    assert params[:3] == ("", "", "")


# ---------------------------------------------------------------------------
# 附：_read_source 缺表 fail-fast
# ---------------------------------------------------------------------------
class _MissingTablePool:
    def connection(self, *_a: Any, **_k: Any) -> Any:
        raise RuntimeError('relation "sql_ddl" does not exist')


async def test_read_source_missing_table_fails_fast():
    with pytest.raises(RuntimeError, match="sql_ddl"):
        await _read_source(_MissingTablePool())
