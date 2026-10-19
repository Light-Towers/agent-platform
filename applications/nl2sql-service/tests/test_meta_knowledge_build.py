# -*- coding: utf-8 -*-
"""元知识构建入口与幂等重建用例（2026-10-18，方案 P0-1 / P0-2 / D2）。

钉五件事（对应任务 2.1 的五条判据）：
1. 同输入连跑两次，行数与内容完全一致（upsert 不翻倍）；
2. 改一条注释只更新那一行（差异最小，不是整表重写）；
3. 源删一条 + prune 后旧行消失（差异重建的另一半）；
4. search_text 非空且 value_tsvector 生成列有值——**需真实 PG**，
   本机无库时是手动步骤（见文件末 skipif 用例内的手动命令）；
5. embedding 维度不符直接抛错，不静默写坏数据。

另钉 P0-1 的审计补款（D2）：列/指标/值三类都有 embedding 写入路径，
且 upsert 的列清单写死（禁 data.keys() 动态拼列）。

fake 池实现的是 001 DDL 唯一键上的 upsert/prune **语义**，不是"什么都接受"
的录音机——不认识的 SQL 形状直接断言失败，防止测试靠假仓库变绿。
"""

from __future__ import annotations

import copy
import os
import re
from typing import Any

import pytest
from nl2sql_service.repositories.postgres.meta.meta_repository import MetaRepository
from nl2sql_service.services.meta_knowledge_service import MetaKnowledgeService
from nl2sql_service.tokenizer import tokenize

_SCOPE = ("tenant_id", "workspace_id", "datasource_id")

_TABLES = [
    {
        "table_name": "orders",
        "table_comment": "订单表",
        "columns": [
            {"column_name": "order_id", "column_comment": "订单ID", "data_type": "bigint"},
            {"column_name": "amount", "column_comment": "订单金额", "data_type": "numeric"},
        ],
    },
    {
        "table_name": "customers",
        "table_comment": "客户表",
        "columns": [
            {"column_name": "customer_name", "column_comment": "客户名称", "data_type": "varchar"},
        ],
    },
]
_METRICS = [{"metric_name": "销售额", "metric_desc": "订单金额合计", "metric_expr": "SUM(orders.amount)"}]
_VALUES = [
    # #117：table_name 是独立列（同名列跨表共存与回溯）；column_name 保持历史形状
    {"table_name": "customers", "column_name": "customers.customer_name", "value": "VIP", "value_desc": "VIP 客户"},
    {"table_name": "orders", "column_name": "order_status", "value": "已支付", "value_desc": ""},
]
#: §5.14-R1 轻量声明：关系（不造 DSL）+ 别名（P0-5 别名精确匹配的登记处）
_RELATIONS = [
    {
        "left_table": "orders",
        "left_column": "customer_id",
        "right_table": "customers",
        "right_column": "customer_id",
        "relation_type": "many_to_one",
        "note": "同名不同义时以声明为准",
    }
]
_ALIASES = [
    {"target_kind": "metric", "target_name": "销售额", "alias": "GMV", "source": "human"},
    {"target_kind": "column", "target_name": "orders.amount", "alias": "成交金额", "source": "human"},
]


# ---------------------------------------------------------------------------
# fake 池：001 唯一键上的 upsert/prune 语义
# ---------------------------------------------------------------------------
class _FakeCursor:
    def __init__(self, row: tuple | None = None, rowcount: int = 0) -> None:
        self._row = row
        self.rowcount = rowcount

    async def fetchone(self) -> tuple | None:
        return self._row


class _FakeConn:
    def __init__(self, pool: "_FakePool") -> None:
        self._pool = pool

    async def execute(self, sql: str, params: tuple | None = None) -> _FakeCursor:
        return self._pool._execute(sql, params)

    async def __aenter__(self) -> "_FakeConn":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakePool:
    """内存 PG 子集：按唯一键 upsert、按作用域 prune。

    只认本仓储生成的两种 SQL 形状；别的形状 AssertionError——fake 的契约
    与 001 DDL 对齐，跑绿即证明 SQL 形状没漂。
    """

    def __init__(self) -> None:
        self.store: dict[str, dict[tuple, dict[str, Any]]] = {}
        self.history: list[tuple[str, tuple]] = []

    def connection(self, *_args: Any, **_kwargs: Any) -> _FakeConn:
        return _FakeConn(self)

    def rows(self, table: str) -> list[dict[str, Any]]:
        return list(self.store.get(table, {}).values())

    def snapshot(self) -> dict[str, list[str]]:
        return {table: sorted(repr(r) for r in rows) for table, rows in self.store.items()}

    def _execute(self, sql: str, params: tuple | None) -> _FakeCursor:
        normalized = " ".join(sql.split())
        self.history.append((normalized, tuple(params or ())))
        m = re.match(r"INSERT INTO (\w+) \(([^)]*)\) VALUES", normalized)
        if m:
            return self._upsert(m.group(1), [c.strip() for c in m.group(2).split(",")], normalized, tuple(params or ()))
        m = re.match(r"DELETE FROM (\w+)", normalized)
        if m:
            return self._delete(m.group(1), normalized, tuple(params or ()))
        raise AssertionError(f"fake pool 不认识的 SQL 形状: {normalized}")

    def _upsert(self, table: str, cols: list[str], sql: str, params: tuple) -> _FakeCursor:
        conflict = re.search(r"ON CONFLICT \(([^)]*)\) DO UPDATE", sql)
        assert conflict, f"upsert 缺 ON CONFLICT（唯一键）: {sql}"
        key_cols = [c.strip() for c in conflict.group(1).split(",")]
        natural = [c for c in key_cols if c not in _SCOPE]
        assert len(params) == len(cols), f"参数个数与列清单不符: {len(params)} vs {len(cols)}"
        row = dict(zip(cols, params))
        table_rows = self.store.setdefault(table, {})
        key = tuple(row[c] for c in natural)
        inserted = key not in table_rows
        table_rows[key] = row
        # RETURNING (xmax = 0) AS inserted：连接配 dict_row ⇒ fetchone 返回 dict
        return _FakeCursor(row={"inserted": inserted})

    def _delete(self, table: str, sql: str, params: tuple) -> _FakeCursor:
        rows = self.store.get(table, {})
        keep_match = re.search(r"AND \(([^)]+)\) NOT IN \(VALUES", sql)
        if not keep_match:
            deleted = len(rows)
            self.store[table] = {}
            return _FakeCursor(rowcount=deleted)
        natural = [c.strip() for c in keep_match.group(1).split(",")]
        assert params[:3] == ("", "", ""), f"prune 必须按作用域删除，实际前三个参数={params[:3]}"
        rest = params[3:]
        assert len(rest) % len(natural) == 0, f"prune 参数个数与自然键宽度不符: {rest}"
        width = len(natural)
        keep = {rest[i * width : (i + 1) * width] for i in range(len(rest) // width)}
        stale = [k for k, row in rows.items() if tuple(row[c] for c in natural) not in keep]
        for k in stale:
            del rows[k]
        return _FakeCursor(rowcount=len(stale))


class _StubEmbedder:
    """定长向量 + 记录调用文本（证三类都写 embedding、维度被校验）。"""

    def __init__(self, dim: int = 8) -> None:
        self.dim = dim
        self.texts: list[str] = []

    async def embed_query(self, text: str) -> list[float]:
        self.texts.append(text)
        return [0.1] * self.dim


def _service(pool: _FakePool, embedder: Any = None, vector_dim: int = 8, tokenizer: str = "bigram") -> MetaKnowledgeService:
    return MetaKnowledgeService(
        meta_repo=MetaRepository(pool=pool),
        embedder=embedder,
        tokenizer=tokenizer,
        vector_dim=vector_dim,
    )


async def _build_all(service: MetaKnowledgeService) -> dict[str, dict[str, int]]:
    return {
        "columns": await service.build_from_tables(copy.deepcopy(_TABLES)),
        "metrics": await service.build_from_metrics(copy.deepcopy(_METRICS)),
        "values": await service.build_from_values(copy.deepcopy(_VALUES)),
        "relations": await service.build_from_relations(copy.deepcopy(_RELATIONS)),
        "aliases": await service.build_from_aliases(copy.deepcopy(_ALIASES)),
    }


def _comments(pool: _FakePool) -> dict[tuple[str, str], str]:
    return {
        (r["table_name"], r["column_name"]): r["column_comment"]
        for r in pool.rows("nl2sql_column_info")
    }


# ---------------------------------------------------------------------------
# ① 幂等：连跑两次行数一致
# ---------------------------------------------------------------------------
async def test_rebuild_twice_keeps_rows_and_content_identical():
    pool = _FakePool()
    service = _service(pool)
    first = await _build_all(service)
    snapshot = pool.snapshot()
    second = await _build_all(service)

    assert pool.snapshot() == snapshot, "第二次构建改变了库内容（upsert 不幂等）"
    assert len(pool.rows("nl2sql_column_info")) == 3, "列行翻倍（H3 复现）"
    assert first["columns"] == {"inserted": 3, "updated": 0}
    assert second["columns"] == {"inserted": 0, "updated": 3}
    assert second["metrics"] == {"inserted": 0, "updated": 1}
    assert second["values"] == {"inserted": 0, "updated": 2}
    assert second["relations"] == {"inserted": 0, "updated": 1}
    assert second["aliases"] == {"inserted": 0, "updated": 2}
    assert len(pool.rows("nl2sql_relation_info")) == 1
    assert len(pool.rows("nl2sql_alias_info")) == 2


# ---------------------------------------------------------------------------
# ② 改一条注释只更新那一行
# ---------------------------------------------------------------------------
async def test_changing_one_comment_updates_only_that_row():
    pool = _FakePool()
    service = _service(pool)
    await _build_all(service)
    before = _comments(pool)

    tables = copy.deepcopy(_TABLES)
    tables[0]["columns"][1]["column_comment"] = "订单金额（含税）"
    stats = await service.build_from_tables(tables)

    after = _comments(pool)
    changed = [k for k in after if after[k] != before[k]]
    assert changed == [("orders", "amount")], f"应只更新一行，实际变动={changed}"
    assert stats == {"inserted": 0, "updated": 3}
    assert len(pool.rows("nl2sql_column_info")) == 3


# ---------------------------------------------------------------------------
# ③ prune：源里不存在的行消失
# ---------------------------------------------------------------------------
async def test_prune_removes_rows_absent_from_source():
    pool = _FakePool()
    service = _service(pool)
    await _build_all(service)
    assert len(pool.rows("nl2sql_value_info")) == 2

    values = [_VALUES[0]]  # 源里删掉 order_status/已支付
    await service.build_from_values(values)
    pruned = await service.prune(
        copy.deepcopy(_TABLES), copy.deepcopy(_METRICS), values, copy.deepcopy(_RELATIONS), copy.deepcopy(_ALIASES)
    )

    assert pruned == {
        "columns_deleted": 0,
        "metrics_deleted": 0,
        "values_deleted": 1,
        "relations_deleted": 0,
        "aliases_deleted": 0,
    }
    assert [r["value"] for r in pool.rows("nl2sql_value_info")] == ["VIP"]


# ---------------------------------------------------------------------------
# ④ #117：table_name 进唯一键 + tokenizer 版本标记
# ---------------------------------------------------------------------------
async def test_same_column_name_across_tables_coexists():
    """#117 本体：orders.status 与 venues.status 同值不再撞唯一键，且可回溯所属表。

    修复前：唯一键 (scope..., column_name, value) 无 table_name ⇒ 第二个 insert
    直接 ON CONFLICT 打中第一行（ venues.status 被 upsert 成 orders 的更新），
    且行内无 table_name 连回溯都做不到。
    """
    pool = _FakePool()
    service = _service(pool)
    values = [
        {"table_name": "orders", "column_name": "status", "value": "已支付"},
        {"table_name": "venues", "column_name": "status", "value": "已支付"},
    ]
    stats = await service.build_from_values(values)
    assert stats == {"inserted": 2, "updated": 0}

    rows = pool.rows("nl2sql_value_info")
    assert len(rows) == 2
    assert {r["table_name"] for r in rows} == {"orders", "venues"}


async def test_value_rows_stamp_tokenizer_version():
    """#117 后半：tokenizer 列记录 search_text 的分词器——换分词器后旧行可识别
    （旧 search_text/tsvector 静默失效的标记位）。"""
    pool = _FakePool()
    service = _service(pool, tokenizer="bigram")
    await service.build_from_values([{"table_name": "orders", "column_name": "status", "value": "已支付"}])

    row = pool.rows("nl2sql_value_info")[0]
    assert row["tokenizer"] == "bigram"
    assert row["table_name"] == "orders"


async def test_prune_keep_set_includes_table_name():
    """#117：prune 的 keep 集与唯一键同构（3 元组）——少一维会把另一表的同名行误删。"""
    pool = _FakePool()
    service = _service(pool)
    values = [
        {"table_name": "orders", "column_name": "status", "value": "已支付"},
        {"table_name": "venues", "column_name": "status", "value": "已支付"},
    ]
    await service.build_from_values(values)
    # 只保留 orders 的：venues 行应被删（同 column/value 不同 table_name 不再误保）
    pruned = await service.prune([], [], [values[0]])
    assert pruned["values_deleted"] == 1
    remaining = pool.rows("nl2sql_value_info")
    assert len(remaining) == 1 and remaining[0]["table_name"] == "orders"


async def test_prune_with_empty_source_clears_scope():
    pool = _FakePool()
    service = _service(pool)
    await _build_all(service)

    pruned = await service.prune([], [], [])

    assert pruned == {
        "columns_deleted": 3,
        "metrics_deleted": 1,
        "values_deleted": 2,
        "relations_deleted": 1,
        "aliases_deleted": 2,
    }
    assert pool.rows("nl2sql_column_info") == []
    assert pool.rows("nl2sql_metric_info") == []
    assert pool.rows("nl2sql_value_info") == []
    assert pool.rows("nl2sql_relation_info") == []
    assert pool.rows("nl2sql_alias_info") == []


# ---------------------------------------------------------------------------
# 附：三类都写 embedding（D2：此前 metric/value 无写入路径）
# ---------------------------------------------------------------------------
async def test_all_three_kinds_write_embeddings():
    pool = _FakePool()
    embedder = _StubEmbedder(8)
    await _build_all(_service(pool, embedder=embedder))

    for table in ("nl2sql_column_info", "nl2sql_metric_info", "nl2sql_value_info"):
        rows = pool.rows(table)
        assert rows, f"{table} 无写入"
        for r in rows:
            assert r.get("embedding") and len(r["embedding"]) == 8, f"{table} 存在缺 embedding 的行"
    assert "orders amount 订单金额" in embedder.texts, "列 embedding 文本契约漂移"
    assert any("SUM(orders.amount)" in t for t in embedder.texts), "指标 embedding 文本契约漂移"


# ---------------------------------------------------------------------------
# 附：search_text 契约（value_tsvector 的唯一输入）
# ---------------------------------------------------------------------------
async def test_values_write_search_text_with_shared_tokenizer():
    pool = _FakePool()
    await _service(pool).build_from_values(_VALUES)

    rows = {(r["column_name"], r["value"]): r for r in pool.rows("nl2sql_value_info")}
    for key, row in rows.items():
        expected = " ".join(tokenize(f"{key[0]} {key[1]} {row['value_desc']}", "bigram"))
        assert row["search_text"] == expected, f"{key} 的 search_text 与同一套分词不符"
        assert row["search_text"].strip(), f"{key} 的 search_text 为空 ⇒ 全文路召不到（契约断裂）"


# ---------------------------------------------------------------------------
# ⑤ 维度不符抛错，不写坏数据
# ---------------------------------------------------------------------------
async def test_embedding_dim_mismatch_raises_before_any_write():
    pool = _FakePool()
    service = _service(pool, embedder=_StubEmbedder(dim=3), vector_dim=8)

    with pytest.raises(ValueError, match="维度"):
        await service.build_from_tables(_TABLES)

    assert pool.rows("nl2sql_column_info") == [], "维度不符时必须炸在建库前"


# ---------------------------------------------------------------------------
# 附：upsert 的列清单写死（禁 data.keys() 动态拼列）
# ---------------------------------------------------------------------------
async def test_upsert_sql_uses_fixed_column_list_and_conflict_key():
    pool = _FakePool()
    await _build_all(_service(pool))

    inserts = [s for s, _ in pool.history if s.startswith("INSERT INTO")]
    # 列 3 + 指标 1 + 值 2 + 关系 1 + 别名 2
    assert len(inserts) == 9, f"五类共 9 行，实际 INSERT {len(inserts)} 次"
    for sql in inserts:
        assert "ON CONFLICT (" in sql and "RETURNING (xmax = 0)" in sql, f"upsert 形状不完整: {sql}"
        assert "updated_at = now()" in sql, f"DO UPDATE 缺 updated_at: {sql}"
        # 值全部参数化：SQL 文本里不允许出现 YAML 派生文本（注释/表达式）
        assert "订单金额" not in sql and "SUM(orders.amount)" not in sql, f"疑似值拼进了 SQL: {sql}"

    column_insert = next(s for s in inserts if s.startswith("INSERT INTO nl2sql_column_info"))
    assert column_insert.startswith(
        "INSERT INTO nl2sql_column_info "
        "(tenant_id, workspace_id, datasource_id, table_name, column_name, "
        "table_comment, column_comment, data_type, embedding) VALUES"
    ), f"列清单写死契约漂移: {column_insert}"
    assert (
        "ON CONFLICT (tenant_id, workspace_id, datasource_id, table_name, column_name)" in column_insert
    ), "列冲突键必须与 001 的 uq_nl2sql_column 对齐"

    value_insert = next(s for s in inserts if s.startswith("INSERT INTO nl2sql_value_info"))
    assert "search_text" in value_insert, "取值 upsert 必须写 search_text（value_tsvector 唯一输入）"

    relation_insert = next(s for s in inserts if s.startswith("INSERT INTO nl2sql_relation_info"))
    assert (
        "ON CONFLICT (tenant_id, workspace_id, datasource_id, left_table, left_column, "
        "right_table, right_column)" in relation_insert
    ), "关系冲突键必须与 001 的 uq_nl2sql_relation 对齐"

    alias_insert = next(s for s in inserts if s.startswith("INSERT INTO nl2sql_alias_info"))
    assert (
        "ON CONFLICT (tenant_id, workspace_id, datasource_id, target_kind, target_name, alias)" in alias_insert
    ), "别名冲突键必须与 001 的 uq_nl2sql_alias 对齐"


async def test_relations_and_aliases_write_without_embedding():
    """关系/别名是精确匹配表（001 DDL 无 embedding 列）——不许画蛇添足加向量。"""
    pool = _FakePool()
    await _build_all(_service(pool, embedder=_StubEmbedder(8)))

    for table in ("nl2sql_relation_info", "nl2sql_alias_info"):
        rows = pool.rows(table)
        assert rows, f"{table} 无写入"
        for row in rows:
            assert "embedding" not in row, f"{table} 不该有 embedding 列（001 DDL 没有）"


async def test_relation_and_alias_prune_removes_absent_declarations():
    pool = _FakePool()
    service = _service(pool)
    await _build_all(service)

    # 源里删掉 GMV 别名
    pruned = await service.prune([], [], [], copy.deepcopy(_RELATIONS), [_ALIASES[1]])
    assert pruned["aliases_deleted"] == 1
    assert [a["alias"] for a in pool.rows("nl2sql_alias_info")] == ["成交金额"]
    assert len(pool.rows("nl2sql_relation_info")) == 1


# ---------------------------------------------------------------------------
# 附：CLI 只接受 MetricConfig（运行契约单源）
# ---------------------------------------------------------------------------
def test_load_metric_config_rejects_non_mapping(tmp_path):
    from nl2sql_service.scripts.build_meta_knowledge import load_metric_config

    bad = tmp_path / "bad.yaml"
    bad.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ValueError, match="mapping"):
        load_metric_config(str(bad))


def test_load_example_config_as_metric_config():
    from pathlib import Path

    from nl2sql_service.scripts.build_meta_knowledge import load_metric_config

    example = Path(__file__).resolve().parents[1] / "nl2sql_service" / "config" / "metric_config.example.yaml"
    config = load_metric_config(str(example))
    assert config.tables and config.columns and config.metrics and config.values


def test_tables_from_config_keeps_orphan_columns():
    from nl2sql_service.config.metric_config_schema import MetricConfig
    from nl2sql_service.scripts.build_meta_knowledge import tables_from_config

    config = MetricConfig(
        tables=[{"table_name": "orders", "table_comment": "订单表"}],
        columns=[
            {"table_name": "orders", "column_name": "amount", "column_comment": "金额", "data_type": "numeric"},
            {"table_name": "ghost", "column_name": "x", "column_comment": "", "data_type": ""},
        ],
    )
    tables = tables_from_config(config)
    assert tables[0]["table_comment"] == "订单表"
    assert tables[0]["columns"][0]["column_name"] == "amount"
    ghost = next(t for t in tables if t["table_name"] == "ghost")
    assert ghost["columns"], "tables 段未声明的表名不能静默丢列（丢列=少一路召回且无报错）"


# ---------------------------------------------------------------------------
# ④ 真库用例（手动步骤）：search_text 非空 + value_tsvector 生成列有值
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    not os.environ.get("META_DB_DSN"),
    reason="需真实 PG（本机无库）。手动步骤：先 init_meta_schema 建表，再设 META_DB_DSN 跑 -k real_pg",
)
async def test_value_search_text_and_tsvector_on_real_pg():
    """④ 的实库判据：fake 池证不了生成列，必须真 PG。

    手动步骤：
        python -m nl2sql_service.scripts.init_meta_schema --dsn "$META_DB_DSN"
        META_DB_DSN="..." uv run pytest applications/nl2sql-service/tests \\
            ::test_meta_knowledge_build.py -k real_pg -q
    """
    from nl2sql_service.clients.postgres_client_manager import PostgresClientManager
    from nl2sql_service.conf.settings import get_settings

    settings = get_settings()
    dsn = os.environ["META_DB_DSN"]
    values = [{"column_name": "order_status", "value": "已支付", "value_desc": "订单已支付"}]

    pg = PostgresClientManager(dsn, name="meta-build-test", statement_timeout_ms=10_000)
    await pg.connect()
    try:
        service = MetaKnowledgeService(
            meta_repo=MetaRepository(pool=pg.pool, table_prefix=settings.table_prefix),
            embedder=None,  # 本用例只验 search_text/tsvector，不需要向量
            tokenizer=settings.tokenizer,
            vector_dim=settings.vector_dim,
        )
        await service.build_from_values(values)
        async with pg.pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT search_text, value_tsvector::text FROM {settings.table_prefix}value_info "
                "WHERE column_name = %s AND value = %s",
                ("order_status", "已支付"),
            )
            row = await cur.fetchone()
        assert row is not None, "build_from_values 未写入行"
        assert row[0] and row[0].strip(), f"search_text 为空 ⇒ 全文路召不到: {row[0]!r}"
        assert row[1], f"value_tsvector 为空（search_text 契约断裂）: {row[1]!r}"
    finally:
        async with pg.pool.connection() as conn:
            await conn.execute(
                f"DELETE FROM {settings.table_prefix}value_info WHERE column_name = %s AND value = %s",
                ("order_status", "已支付"),
            )
        await pg.close()
