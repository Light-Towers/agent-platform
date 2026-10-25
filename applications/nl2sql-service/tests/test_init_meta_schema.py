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
#: v2 增量（002_meta_lifecycle）：多轮 session / 查询追溯 / 表统计
_EXPECTED_TABLES_V2 = (
    "nl2sql_session_state",
    "nl2sql_query_trace",
    "nl2sql_table_stats",
)


def test_migrations_discovered_in_version_order():
    migrations = load_migrations(1536)
    assert migrations, "未发现任何 *.up.sql"
    names = [name for name, _ in migrations]
    assert names == sorted(names), f"迁移未按文件名排序：{names}"
    assert names[0].startswith("001_")
    assert "002_meta_lifecycle.up.sql" in names, f"缺 v2 迁移: {names}"


def test_v2_migration_covers_lifecycle_tables():
    sql = dict(load_migrations(1536))["002_meta_lifecycle.up.sql"]
    for table in _EXPECTED_TABLES_V2:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql, f"缺 v2 建表语句：{table}"
    # 四元组/追溯的关键列在位（§5.13-M2 / P0-4 判据的落库对象）
    for column in ("quadruple", "confirmed_pairs", "meta_revision", "source_snapshot", "unmatched_terms", "row_estimate"):
        assert column in sql, f"v2 缺关键列: {column}"


def test_v2_migration_is_idempotent_and_has_no_drop():
    sql = dict(load_migrations(1536))["002_meta_lifecycle.up.sql"]
    assert "DROP " not in sql.upper(), "up 迁移不得包含 DROP"
    assert sql.count("CREATE TABLE IF NOT EXISTS") == 3
    assert sql.count("CREATE INDEX IF NOT EXISTS") == 3
    assert "ON CONFLICT (key) DO UPDATE" in sql, "版本标记必须幂等"


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


# ---------------------------------------------------------------------------
# #110：对账路径与并发互斥（不连真 PG——用假连接捕获 SQL 序列与 information_schema 实况）
# ---------------------------------------------------------------------------
from nl2sql_service.scripts.init_meta_schema import apply, expected_schema, verify_applied  # noqa: E402


class _FakeCursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    async def fetchall(self) -> list[dict]:
        return self._rows


class _FakeConn:
    """捕获全部 execute（SQL + 参数）；information_schema 查询返回脚本化的实况行。"""

    def __init__(self, actual_rows: list[dict]) -> None:
        self.statements: list[tuple[str, tuple]] = []
        self._actual_rows = actual_rows

    async def execute(self, sql: str, params: tuple | None = None):
        self.statements.append((sql, params or ()))
        if "information_schema.columns" in sql:
            return _FakeCursor(self._actual_rows)
        return _FakeCursor([])


class _NullAsyncCtx:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _FakeConn:
        return self._conn

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self.conn = conn
        self.opened = False

    def connection(self) -> _NullAsyncCtx:
        return _NullAsyncCtx(self.conn)

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.opened = False


def _full_actual_rows() -> list[dict]:
    """按迁移声明构造"全部落地"的 information_schema 实况（无差异）。"""
    rows: list[dict] = []
    for table, columns in expected_schema([sql for _, sql in load_migrations(1536)]).items():
        rows.extend({"table_name": table, "column_name": c} for c in columns)
    return rows


def test_expected_schema_extracts_tables_and_columns():
    expected = expected_schema([sql for _, sql in load_migrations(1536)])
    for table in _EXPECTED_TABLES + _EXPECTED_TABLES_V2:
        assert table in expected, f"对账解析漏表: {table}"
    value_cols = expected["nl2sql_value_info"]
    assert {"search_text", "value_tsvector", "column_name", "value"} <= value_cols
    assert "constraint" not in value_cols, "CONSTRAINT 行不得被当作列"


async def test_apply_takes_advisory_lock_before_migrations():
    """apply 首语句必须是 advisory lock（#110）：IF NOT EXISTS 并非并发安全。"""
    from unittest.mock import patch

    conn = _FakeConn(_full_actual_rows())
    with patch("agent_runtime.pool_factory.create_pool", return_value=_FakePool(conn)):
        _applied, problems = await apply("postgresql://u:p@h/db", 1536)
    assert problems == [], "全落地实况不应报差异"
    first_sql, first_params = conn.statements[0]
    assert "pg_advisory_xact_lock" in first_sql
    assert len(first_params) == 1 and isinstance(first_params[0], int), "锁键应为单个整数"


async def test_verify_reports_missing_columns():
    """旧形状库（缺 search_text/value_tsvector）⇒ 差异条目点名缺列。"""
    rows = [
        r
        for r in _full_actual_rows()
        if not (r["table_name"] == "nl2sql_value_info" and r["column_name"] in {"search_text", "value_tsvector"})
    ]
    expected = expected_schema([sql for _, sql in load_migrations(1536)])
    problems = await verify_applied(_FakeConn(rows), expected)
    assert problems == ["nl2sql_value_info 缺列: search_text, value_tsvector"]


async def test_verify_reports_missing_table():
    rows = [r for r in _full_actual_rows() if r["table_name"] != "nl2sql_alias_info"]
    expected = expected_schema([sql for _, sql in load_migrations(1536)])
    problems = await verify_applied(_FakeConn(rows), expected)
    assert problems == ["缺表: nl2sql_alias_info"]


def test_main_exits_nonzero_on_verification_problems(capsys):
    """对账不齐 ⇒ 非零退出 + 差异打全（不让"已应用 N 个迁移"掩盖半初始化）。"""
    from unittest.mock import AsyncMock, patch

    with patch(
        "nl2sql_service.scripts.init_meta_schema.apply",
        new=AsyncMock(return_value=(["001_meta_schema.up.sql"], ["nl2sql_value_info 缺列: search_text"])),
    ):
        rc = main(["--dsn", "postgresql://u:p@127.0.0.1:5432/x", "--vector-dim", "1536"])
    assert rc == 2
    out = capsys.readouterr().out
    assert "校验未通过" in out and "缺列: search_text" in out


def test_ddl_records_vector_dim_in_schema_meta():
    sql = load_migrations(1536)[0][1]
    assert "INSERT INTO nl2sql_schema_meta (key, value) VALUES ('vector_dim', '1536')" in sql


def test_ddl_has_reconciliation_alters_for_value_info():
    """存量旧形状库的对账路径：幂等补列（#110）。"""
    sql = load_migrations(1536)[0][1]
    assert "ALTER TABLE nl2sql_value_info ADD COLUMN IF NOT EXISTS search_text" in sql
    assert "ALTER TABLE nl2sql_value_info ADD COLUMN IF NOT EXISTS value_tsvector" in sql


def test_ddl_gin_index_is_do_block_protected():
    """GIN 索引与 ANN 同纪律：失败只告警不中止整批。"""
    sql = load_migrations(1536)[0][1]
    gin_block = sql[sql.index("idx_nl2sql_value_tsv") - 200 : sql.index("idx_nl2sql_value_tsv") + 120]
    assert "DO $$" in gin_block and "EXCEPTION WHEN OTHERS THEN" in gin_block
