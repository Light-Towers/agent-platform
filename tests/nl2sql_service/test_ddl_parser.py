"""DDL 解析与文档关联用例（A 方案 Stage ②，2026-10-18）。

钉八件事：
1. CREATE TABLE → 列行（列名 + 类型），表级约束不产列行；
2. COMMENT ON TABLE/COLUMN → 表/列注释（可前置于 CREATE，后写覆盖）；
3. CREATE INDEX/VIEW 等无关语句静默跳过、不进 skipped（噪声≠异常）；
4. 同名表重复 CREATE 保留首见并记 skipped（不静默合并）；
5. 解析整体失败/空文本：返回空 + 记账，不抛不编；
6. 文档→表：词边界匹配（order 不命中 orders 前缀、user 不命中 user_log）；
7. 文档命中多表同时挂；未命中任何表的文档进 unmapped（不静默丢）；
8. 形状与 build_from_tables 输入契约一致（table_name/table_comment/columns）。
"""

from __future__ import annotations

from nl2sql_service.ddl_parser import associate_docs_with_tables, parse_ddl

_DDL = """
-- 订单表
CREATE TABLE orders (
    id BIGINT PRIMARY KEY,
    customer_id BIGINT NOT NULL,
    amount NUMERIC(10,2) DEFAULT 0,
    status VARCHAR(20) DEFAULT 'PENDING'
);
CREATE TABLE customers (customer_id BIGINT, customer_name VARCHAR(50));
COMMENT ON TABLE orders IS '订单主表';
COMMENT ON COLUMN orders.amount IS '订单金额（含税）';
CREATE INDEX idx_orders_status ON orders (status);
"""


def test_parse_ddl_extracts_tables_and_columns():
    tables, skipped = parse_ddl(_DDL)
    assert skipped == []
    assert [t["table_name"] for t in tables] == ["orders", "customers"]

    orders = tables[0]
    assert orders["table_comment"] == "订单主表"
    assert [(c["column_name"], c["data_type"]) for c in orders["columns"]] == [
        ("id", "BIGINT"),
        ("customer_id", "BIGINT"),
        ("amount", "DECIMAL(10, 2)"),
        ("status", "VARCHAR(20)"),
    ], "表级约束（PRIMARY KEY/NOT NULL/DEFAULT）不改变列行形状"
    amount = next(c for c in orders["columns"] if c["column_name"] == "amount")
    assert amount["column_comment"] == "订单金额（含税）"
    assert next(c for c in orders["columns"] if c["column_name"] == "id")["column_comment"] == ""


def test_parse_ddl_shape_matches_build_from_tables_contract():
    tables, _ = parse_ddl(_DDL)
    for table in tables:
        assert set(table) == {"table_name", "table_comment", "columns"}
        for column in table["columns"]:
            assert set(column) == {"column_name", "data_type", "column_comment"}


def test_comment_before_create_and_last_write_wins():
    tables, _ = parse_ddl(
        "COMMENT ON TABLE orders IS '第一版';"
        "CREATE TABLE orders (id BIGINT);"
        "COMMENT ON TABLE orders IS '第二版';"
    )
    assert tables[0]["table_comment"] == "第二版", "COMMENT ON 后写覆盖（可前置于 CREATE）"


def test_irrelevant_statements_are_silent_not_skipped():
    tables, skipped = parse_ddl(
        "CREATE TABLE t (id BIGINT);"
        "CREATE INDEX idx ON t (id);"
        "CREATE VIEW v AS SELECT 1;"
    )
    assert [t["table_name"] for t in tables] == ["t"]
    assert skipped == [], "CREATE INDEX/VIEW 与元知识无关：静默跳过，不记账（噪声≠异常）"


def test_duplicate_create_table_keeps_first_and_records():
    tables, skipped = parse_ddl(
        "CREATE TABLE t (id BIGINT); CREATE TABLE t (id BIGINT, extra TEXT);"
    )
    assert len(tables) == 1
    assert [c["column_name"] for c in tables[0]["columns"]] == ["id"], "保留首见，不静默合并"
    assert any("duplicate CREATE TABLE t" in s for s in skipped)


def test_unparseable_ddl_returns_empty_and_records():
    """坏 DDL 必须响：sqlglot 对解析不了的语句 fallback 成 Command 且不抛
    （error_level=RAISE 实测也不抛）——静默丢 = 迁移缺列且无痕。"""
    tables, skipped = parse_ddl("CREATE TABEL oops (")
    assert tables == []
    assert skipped and "unparsed statement" in skipped[0]


def test_alter_and_drop_are_recorded_not_silent():
    tables, skipped = parse_ddl("CREATE TABLE t (id BIGINT); ALTER TABLE t ADD COLUMN x TEXT;")
    assert [t["table_name"] for t in tables] == ["t"]
    assert any("unsupported DDL" in s and "ALTER" in s for s in skipped), "良构但不处理的 DDL 也要记账"


def test_empty_ddl_is_empty_not_error():
    assert parse_ddl("") == ([], [])
    assert parse_ddl("   \n  ") == ([], [])


def test_doc_association_word_boundaries():
    by_table, unmapped = associate_docs_with_tables(
        # 句中没有独立 "orders"——唯一出现在 "orders_log" 内，必须被词边界挡掉
        ["order 的祖先表是 orders_log", "user_log 与 user 是两张表"],
        ["orders", "user", "user_log", "orders_log"],
    )
    assert by_table.get("orders_log") == ["order 的祖先表是 orders_log"]
    assert "orders" not in by_table, "orders_log 内的 orders 子串不得误命中 orders"
    assert by_table.get("user") == ["user_log 与 user 是两张表"], "独立的 user 必须命中（词边界不误伤）"
    assert by_table.get("user_log") == ["user_log 与 user 是两张表"]
    assert unmapped == []


def test_doc_multi_hit_and_unmapped_recorded():
    docs = ["orders 与 customers 通过 customer_id 关联", "通用运维手册"]
    by_table, unmapped = associate_docs_with_tables(docs, ["orders", "customers"])
    assert by_table["orders"] == [docs[0]]
    assert by_table["customers"] == [docs[0]], "同一文档命中多表同时挂（一篇联查说明服务两处）"
    assert unmapped == ["通用运维手册"], "未命中任何表名的文档必须进 unmapped（不静默丢）"


def test_doc_matching_is_case_insensitive_and_order_preserving():
    docs = ["先讲 ORDERS", "再讲 Orders 的状态机"]
    by_table, unmapped = associate_docs_with_tables(docs, ["orders"])
    assert by_table["orders"] == docs, "大小写不敏感 + 按输入序保序"
    assert unmapped == []
