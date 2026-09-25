"""agent_runtime.migrations 单元测试。

覆盖：
- base.py: Migration dataclass 文件读取 + checksum + discover 目录扫描
- runner.py: 全新库 apply / 存量库 stamp / 失败中止 / 幂等
- 真实 .sql 文件: discover 可达性验证
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers: fake pool/connection 模拟 psycopg 行为
# ---------------------------------------------------------------------------


class FakeConnection:
    """最小 async connection mock，记录执行的 SQL。"""

    def __init__(self, *, fail_on: str | None = None, existing_tables: set[str] | None = None):
        self.executed: list[tuple[str, Any]] = []
        self._fail_on = fail_on
        self._existing_tables = existing_tables or set()

    async def execute(self, sql: str, params: Any = None) -> "FakeCursor":
        if self._fail_on and self._fail_on in sql:
            raise RuntimeError(f"Simulated failure on: {self._fail_on}")
        self.executed.append((sql, params))
        return FakeCursor(sql, self)

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class FakeCursor:
    def __init__(self, sql: str, conn: FakeConnection):
        self._sql = sql
        self._conn = conn

    async def fetchone(self):
        if "MAX(version)" in self._sql:
            max_v = 0
            for sql, params in self._conn.executed:
                if "INSERT INTO schema_migrations" in sql and params:
                    max_v = max(max_v, params[0])
            return (max_v,)
        return None

    async def fetchall(self):
        if "schema_migrations" in self._sql:
            return [params for sql, params in self._conn.executed
                    if "INSERT INTO schema_migrations" in sql and params]
        if "information_schema.tables" in self._sql:
            return [(name,) for name in self._conn._existing_tables]
        return []


class FakePool:
    def __init__(self, conn: FakeConnection):
        self._conn = conn

    def connection(self):
        return self._conn


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sql_dir(tmp_path: Path):
    """创建临时目录放测试用 .sql 文件，返回 Migration 列表。"""
    up1 = tmp_path / "001_init.up.sql"
    up1.write_text("CREATE TABLE IF NOT EXISTS t1 (id INT);")
    up2 = tmp_path / "002_add_col.up.sql"
    up2.write_text("ALTER TABLE t1 ADD COLUMN IF NOT EXISTS name TEXT;")
    down2 = tmp_path / "002_add_col.down.sql"
    down2.write_text("ALTER TABLE t1 DROP COLUMN IF EXISTS name;")
    return tmp_path


@pytest.fixture(autouse=True)
def _reset():
    from agent_runtime.migrations.base import reset

    reset()
    yield
    reset()


# ---------------------------------------------------------------------------
# Tests: base.py
# ---------------------------------------------------------------------------


class TestMigrationFileReading:
    def test_read_up(self, sql_dir: Path):
        from agent_runtime.migrations.base import Migration

        m = Migration(
            version=1,
            name="init",
            up_sql=sql_dir / "001_init.up.sql",
        )
        assert "CREATE TABLE" in m.read_up()

    def test_read_down(self, sql_dir: Path):
        from agent_runtime.migrations.base import Migration

        m = Migration(
            version=2,
            name="add_col",
            up_sql=sql_dir / "002_add_col.up.sql",
            down_sql=sql_dir / "002_add_col.down.sql",
        )
        assert "DROP COLUMN" in m.read_down()

    def test_read_down_none(self, sql_dir: Path):
        from agent_runtime.migrations.base import Migration

        m = Migration(
            version=1,
            name="init",
            up_sql=sql_dir / "001_init.up.sql",
            down_sql=None,
        )
        assert m.read_down() is None

    def test_checksum_deterministic(self, sql_dir: Path):
        from agent_runtime.migrations.base import Migration

        m = Migration(
            version=1,
            name="init",
            up_sql=sql_dir / "001_init.up.sql",
        )
        assert m.checksum() == m.checksum()
        assert len(m.checksum()) == 16


class TestDiscovery:
    def test_discovers_from_directory(self, sql_dir: Path):
        from agent_runtime.migrations.base import discover

        migrations = discover(directory=sql_dir)
        assert len(migrations) == 2
        assert migrations[0].version == 1
        assert migrations[1].version == 2
        assert migrations[1].down_sql is not None

    def test_discovers_real_sql_files(self):
        """真实 migrations/ 目录下的 .sql 文件应被自动发现。"""
        from agent_runtime.migrations.base import discover

        migrations = discover()
        assert len(migrations) >= 3
        versions = [m.version for m in migrations]
        assert versions == sorted(versions)
        assert 1 in versions
        assert 2 in versions
        assert 3 in versions

    def test_real_migrations_have_sql_content(self):
        from agent_runtime.migrations.base import discover

        for m in discover():
            sql = m.read_up()
            assert len(sql) > 10, f"v{m.version} SQL file seems empty"


class TestTenantMigrationsRollback:
    """v4/v5 租户迁移必须成对可回滚（评审 Warning#8）。

    惯例基准：002/003 均有 down；v4/v5 引入的 tenant_id 列若无回滚出口，
    升级失败时无法退回，故 here 钉住：两者必须存在 down 且内容与 up 对称。
    """

    def _get(self, version: int):
        from agent_runtime.migrations.base import discover

        return next(m for m in discover() if m.version == version)

    def test_v4_has_down_that_drops_tenant_column(self):
        m = self._get(4)
        assert m.down_sql is not None, "v4 tenant_id 迁移缺 down，不可回滚"
        down = m.read_down()
        assert "DROP COLUMN IF EXISTS tenant_id" in down
        assert "DROP INDEX IF EXISTS idx_memories_tenant" in down

    def test_v5_has_down_that_restores_column_default(self):
        m = self._get(5)
        assert m.down_sql is not None, "v5 tenant 强制迁移缺 down，不可回滚"
        down = m.read_down()
        # up 把列默认值改为 'default'，down 须恢复 v4 的 ''
        assert "SET DEFAULT ''" in down

    def test_v5_up_backfills_empty_tenant_and_sets_default(self):
        m = self._get(5)
        up = m.read_up()
        assert "SET tenant_id = 'default' WHERE tenant_id = ''" in up
        assert "SET DEFAULT 'default'" in up


# ---------------------------------------------------------------------------
# Tests: runner.py
# ---------------------------------------------------------------------------


def _make_test_migrations(tmp_path: Path) -> list:
    """创建临时 .sql 文件并返回 Migration 列表。"""
    from agent_runtime.migrations.base import Migration

    up1 = tmp_path / "001_test.up.sql"
    up1.write_text("SELECT 1;")
    up2 = tmp_path / "002_test2.up.sql"
    up2.write_text("SELECT 2;")
    return [
        Migration(version=1, name="test", up_sql=up1),
        Migration(version=2, name="test2", up_sql=up2),
    ]


class TestFreshDatabase:
    """全新库（无 chunks 表）→ 跑所有 migration。"""

    @pytest.mark.asyncio
    async def test_applies_all_migrations(self, tmp_path: Path):
        from agent_runtime.migrations import runner as runner_mod

        migrations = _make_test_migrations(tmp_path)
        conn = FakeConnection(existing_tables=set())
        pool = FakePool(conn)

        with (
            patch.object(runner_mod, "discover", return_value=migrations),
            patch.object(runner_mod, "_get_vector_dim", return_value=512),
        ):
            applied = await runner_mod.run_migrations(pool)

        assert len(applied) == 2
        # 确认 CREATE TABLE 和 INSERT 记录都执行了
        sqls = [s for s, _ in conn.executed]
        assert any("SELECT 1;" in s for s in sqls)
        inserts = [(s, p) for s, p in conn.executed if "INSERT INTO schema_migrations" in s]
        assert len(inserts) == 2


class TestExistingDatabase:
    """存量库（有 chunks 表但无记录）→ stamp baseline + apply 增量。"""

    @pytest.mark.asyncio
    async def test_stamp_baseline_then_apply_incr(self, tmp_path: Path):
        from agent_runtime.migrations import runner as runner_mod

        migrations = _make_test_migrations(tmp_path)
        from agent_runtime.migrations.runner import _BASELINE_REQUIRED_TABLES
        conn = FakeConnection(existing_tables=set(_BASELINE_REQUIRED_TABLES))
        pool = FakePool(conn)

        with (
            patch.object(runner_mod, "discover", return_value=migrations),
            patch.object(runner_mod, "_get_vector_dim", return_value=512),
        ):
            applied = await runner_mod.run_migrations(pool)

        # baseline (v1) 被 stamp → "SELECT 1;" 不应被执行
        sqls = [s for s, _ in conn.executed]
        assert "SELECT 1;" not in sqls
        # 增量 (v2) 正常执行
        assert "SELECT 2;" in sqls
        # applied = stamped(1) + run(2) = 2
        assert len(applied) == 2


class TestAlreadyUpToDate:
    """版本已最新 → 无操作。"""

    @pytest.mark.asyncio
    async def test_no_pending(self, tmp_path: Path):
        from agent_runtime.migrations import runner as runner_mod

        migrations = _make_test_migrations(tmp_path)
        conn = FakeConnection(existing_tables=set())
        # 预设已有 v1 + v2 记录；checksum 与 migration 文件一致。
        conn.executed.append(("INSERT INTO schema_migrations ...", (2, "test2", migrations[1].checksum())))
        pool = FakePool(conn)

        with (
            patch.object(runner_mod, "discover", return_value=migrations),
            patch.object(runner_mod, "_get_vector_dim", return_value=512),
        ):
            applied = await runner_mod.run_migrations(pool)

        assert len(applied) == 0



class TestBaselineValidation:
    """baseline 只能在完整 schema 上 stamp，半初始化库必须 fail-fast。"""

    @pytest.mark.asyncio
    async def test_partial_existing_schema_is_rejected(self, tmp_path: Path):
        from agent_runtime.migrations import runner as runner_mod

        migrations = _make_test_migrations(tmp_path)
        conn = FakeConnection(existing_tables={"chunks"})
        pool = FakePool(conn)

        with (
            patch.object(runner_mod, "discover", return_value=migrations),
            patch.object(runner_mod, "_get_vector_dim", return_value=512),
        ):
            with pytest.raises(runner_mod.MigrationError, match="incomplete baseline schema"):
                await runner_mod.run_migrations(pool)


class TestChecksumValidation:
    """已应用 migration 的 SQL 文件被修改后必须 fail-fast。"""

    @pytest.mark.asyncio
    async def test_checksum_mismatch_is_rejected(self, tmp_path: Path):
        from agent_runtime.migrations import runner as runner_mod

        migrations = _make_test_migrations(tmp_path)
        conn = FakeConnection(existing_tables=set())
        conn.executed.append(("INSERT INTO schema_migrations ...", (1, "test", "tampered")))
        pool = FakePool(conn)

        with (
            patch.object(runner_mod, "discover", return_value=migrations),
            patch.object(runner_mod, "_get_vector_dim", return_value=512),
        ):
            with pytest.raises(runner_mod.MigrationError, match="checksum mismatch"):
                await runner_mod.run_migrations(pool)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("legacy_sentinel", ["stamped", ""], ids=["stamped", "empty"])
    async def test_legacy_sentinel_checksum_is_backfilled(self, tmp_path: Path, legacy_sentinel: str):
        """旧版 stamp 写入的哨兵 checksum → 不报错，启动时用文件 checksum 回填。"""
        from agent_runtime.migrations import runner as runner_mod

        migrations = _make_test_migrations(tmp_path)
        conn = FakeConnection(existing_tables=set())
        conn.executed.append(("INSERT INTO schema_migrations ...", (1, "test", legacy_sentinel)))
        pool = FakePool(conn)

        with (
            patch.object(runner_mod, "discover", return_value=migrations),
            patch.object(runner_mod, "_get_vector_dim", return_value=512),
        ):
            applied = await runner_mod.run_migrations(pool)

        updates = [
            p for s, p in conn.executed
            if "UPDATE schema_migrations" in s and p and p[1] == 1
        ]
        assert updates == [(migrations[0].checksum(), 1)], "哨兵记录应被回填为文件真实 checksum"
        # v1 已记录 → 仅增量 v2 被应用，不应因哨兵报 MigrationError
        assert [m.version for m in applied] == [2]

    @pytest.mark.asyncio
    async def test_no_update_when_checksum_matches(self, tmp_path: Path):
        """已应用记录 checksum 与文件一致 → 不产生任何 UPDATE（回填仅限哨兵）。"""
        from agent_runtime.migrations import runner as runner_mod

        migrations = _make_test_migrations(tmp_path)
        conn = FakeConnection(existing_tables=set())
        conn.executed.append(("INSERT INTO schema_migrations ...", (1, "test", migrations[0].checksum())))
        pool = FakePool(conn)

        with (
            patch.object(runner_mod, "discover", return_value=migrations),
            patch.object(runner_mod, "_get_vector_dim", return_value=512),
        ):
            applied = await runner_mod.run_migrations(pool)

        assert [m.version for m in applied] == [2]
        assert not any("UPDATE schema_migrations" in s for s, _ in conn.executed)


class TestBaselineTableListDrift:
    """_BASELINE_REQUIRED_TABLES 与 001_baseline.up.sql 必须一致。

    漂移守卫：把新表并入 baseline 或重命名表时，若忘了同步手工清单，
    应在测试阶段变红，而不是线上启动时 fail-fast。
    """

    def test_required_tables_match_baseline_sql(self):
        import re

        from agent_runtime.migrations.base import _MIGRATIONS_DIR
        from agent_runtime.migrations.runner import _BASELINE_REQUIRED_TABLES

        sql = (_MIGRATIONS_DIR / "001_baseline.up.sql").read_text(encoding="utf-8")
        created = set(
            re.findall(
                r"CREATE TABLE IF NOT EXISTS\s+(?:public\.)?(\w+)",
                sql,
                flags=re.IGNORECASE,
            )
        )
        assert created == set(_BASELINE_REQUIRED_TABLES), (
            f"baseline SQL 与手工清单漂移: sql-only={sorted(created - set(_BASELINE_REQUIRED_TABLES))}, "
            f"list-only={sorted(set(_BASELINE_REQUIRED_TABLES) - created)}"
        )


class TestMigrationFailure:
    """迁移 SQL 执行失败 → raise MigrationError。"""

    @pytest.mark.asyncio
    async def test_raises_on_failure(self, tmp_path: Path):
        from agent_runtime.migrations import runner as runner_mod
        from agent_runtime.migrations.base import Migration

        bad_sql = tmp_path / "001_bad.up.sql"
        bad_sql.write_text("THIS WILL FAIL INTENTIONALLY;")
        migrations = [Migration(version=1, name="bad", up_sql=bad_sql)]

        conn = FakeConnection(existing_tables=set(), fail_on="THIS WILL FAIL")
        pool = FakePool(conn)

        with (
            patch.object(runner_mod, "discover", return_value=migrations),
            patch.object(runner_mod, "_get_vector_dim", return_value=512),
        ):
            with pytest.raises(runner_mod.MigrationError, match="bad"):
                await runner_mod.run_migrations(pool)


class TestTemplateSubstitution:
    """SQL 中 {{vector_dim}} 被正确替换。"""

    @pytest.mark.asyncio
    async def test_vector_dim_replaced(self, tmp_path: Path):
        from agent_runtime.migrations import runner as runner_mod
        from agent_runtime.migrations.base import Migration

        sql_file = tmp_path / "001_vec.up.sql"
        sql_file.write_text("CREATE TABLE t (embedding vector({{vector_dim}}));")
        migrations = [Migration(version=1, name="vec", up_sql=sql_file)]

        conn = FakeConnection(existing_tables=set())
        pool = FakePool(conn)

        with (
            patch.object(runner_mod, "discover", return_value=migrations),
            patch.object(runner_mod, "_get_vector_dim", return_value=768),
        ):
            await runner_mod.run_migrations(pool)

        sqls = [s for s, _ in conn.executed]
        assert any("vector(768)" in s for s in sqls)
        assert not any("{{vector_dim}}" in s for s in sqls)


class TestGetVersion:
    @pytest.mark.asyncio
    async def test_returns_zero_for_fresh(self):
        from agent_runtime.migrations.runner import get_current_version

        conn = FakeConnection(existing_tables=set())
        pool = FakePool(conn)
        v = await get_current_version(pool)
        assert v == 0


class TestRollback:
    """rollback 语义：目标之上存在不可回滚 migration 时必须拒绝，不静默跳过。"""

    @pytest.mark.asyncio
    async def test_rollback_rejects_irreversible_above_target(self, tmp_path: Path):
        """v1 无 down、v2 有 down：rollback(target=0) 必须报错而非只回滚 v2。"""
        from agent_runtime.migrations import runner as runner_mod
        from agent_runtime.migrations.base import Migration
        from agent_runtime.migrations.runner import MigrationError

        up1 = tmp_path / "001_init.up.sql"
        up1.write_text("SELECT 1;")  # v1 无 down
        up2 = tmp_path / "002_rev.up.sql"
        up2.write_text("SELECT 2;")
        down2 = tmp_path / "002_rev.down.sql"
        down2.write_text("SELECT -2;")  # v2 可回滚
        migrations = [
            Migration(version=1, name="init", up_sql=up1),
            Migration(version=2, name="rev", up_sql=up2, down_sql=down2),
        ]

        conn = FakeConnection(existing_tables=set())
        pool = FakePool(conn)

        with patch.object(runner_mod, "discover", return_value=migrations):
            with pytest.raises(MigrationError, match="v1"):
                await runner_mod.rollback(pool, target_version=0)

        # 拒绝时不得执行任何 down SQL
        sqls = [s for s, _ in conn.executed]
        assert not any("SELECT -2" in s for s in sqls)

    @pytest.mark.asyncio
    async def test_rollback_applies_reversible_descending(self, tmp_path: Path):
        """全部可回滚时按版本降序执行 down 并删除版本记录。"""
        from agent_runtime.migrations import runner as runner_mod
        from agent_runtime.migrations.base import Migration

        up2 = tmp_path / "002_a.up.sql"
        up2.write_text("SELECT 2;")
        down2 = tmp_path / "002_a.down.sql"
        down2.write_text("SELECT -2;")
        up3 = tmp_path / "003_b.up.sql"
        up3.write_text("SELECT 3;")
        down3 = tmp_path / "003_b.down.sql"
        down3.write_text("SELECT -3;")
        migrations = [
            Migration(version=2, name="a", up_sql=up2, down_sql=down2),
            Migration(version=3, name="b", up_sql=up3, down_sql=down3),
        ]

        conn = FakeConnection(existing_tables=set())
        pool = FakePool(conn)

        with patch.object(runner_mod, "discover", return_value=migrations):
            rolled = await runner_mod.rollback(pool, target_version=1)

        assert [m.version for m in rolled] == [3, 2]
        sqls = [s for s, _ in conn.executed]
        assert sqls.index("SELECT -3;") < sqls.index("SELECT -2;")
        deletes = [(s, p) for s, p in conn.executed if "DELETE FROM schema_migrations" in s]
        assert [d[1][0] for d in deletes] == [3, 2]

    @pytest.mark.asyncio
    async def test_rollback_nothing_above_target(self, tmp_path: Path):
        from agent_runtime.migrations import runner as runner_mod
        from agent_runtime.migrations.base import Migration

        up1 = tmp_path / "001_x.up.sql"
        up1.write_text("SELECT 1;")
        migrations = [Migration(version=1, name="x", up_sql=up1)]

        conn = FakeConnection(existing_tables=set())
        pool = FakePool(conn)

        with patch.object(runner_mod, "discover", return_value=migrations):
            rolled = await runner_mod.rollback(pool, target_version=5)

        assert rolled == []
