"""元知识库 DDL 与初始化入口的静态用例（2026-10-18，方案 §5.17）。

⚠️ 这里**不连真实 PG**：只钉"迁移文件被发现、占位符被替换、幂等语句齐全、
脚本 dry-run 不碰库"四件事。DDL 能否在目标 PG 上执行（pgvector 版本、权限）
须由 `init_meta_schema --dsn ...` 在真实库上验证，不在此用例的证明范围内。
"""

from __future__ import annotations

from nl2sql_service.scripts.init_meta_schema import load_migrations, main

_EXPECTED_TABLES = (
    "nl2sql_column_info",
    "nl2sql_metric_info",
    "nl2sql_value_info",
    "nl2sql_relation_info",
    "nl2sql_alias_info",
    "nl2sql_schema_meta",
)


def test_migrations_discovered_in_version_order():
    migrations = load_migrations(1536)
    assert migrations, "未发现任何 *.up.sql"
    names = [name for name, _ in migrations]
    assert names == sorted(names), f"迁移未按文件名排序：{names}"
    assert names[0].startswith("001_")


def test_vector_dim_placeholder_replaced():
    sql = load_migrations(1024)[0][1]
    assert "vector(1024)" in sql
    assert "{{" not in sql, "存在未替换的模板占位符"


def test_ddl_covers_all_metadata_tables():
    sql = load_migrations(1536)[0][1]
    for table in _EXPECTED_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql, f"缺建表语句：{table}"


def test_ddl_is_idempotent_and_has_no_drop():
    sql = load_migrations(1536)[0][1]
    assert "DROP " not in sql.upper(), "up 迁移不得包含 DROP"
    assert sql.count("CREATE INDEX IF NOT EXISTS") >= 5
    # plpgsql 块必须成对闭合
    assert sql.count("$$") % 2 == 0, "DO $$ 块数量不成对"


def test_value_tsvector_is_generated_from_search_text():
    sql = load_migrations(1536)[0][1]
    assert "GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, coalesce(search_text, '')))" in sql


def test_unique_keys_present_for_upsert():
    sql = load_migrations(1536)[0][1]
    for constraint in (
        "uq_nl2sql_column",
        "uq_nl2sql_metric",
        "uq_nl2sql_value",
        "uq_nl2sql_relation",
        "uq_nl2sql_alias",
    ):
        assert constraint in sql, f"缺幂等 upsert 所需的唯一约束：{constraint}"


def test_dry_run_does_not_connect(capsys):
    rc = main(["--dsn", "postgresql://u:p@127.0.0.1:5432/x", "--dry-run", "--vector-dim", "1536"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "001_meta_schema.up.sql" in out
    assert "vector_dim=1536" in out
