"""L3 真实 PostgreSQL migration 集成测试（P1-1 审计修复，2026-09-25）。

定位原则：**不让 L1 冒充 L3**。`test_schema_migrations.py` 的 FakeConnection 只
记录 SQL 字符串，不经过 psycopg → PostgreSQL 的真实参数适配——tuple 传
``ANY(%s)`` 被适配为 record 导致真实 PG 报 ``malformed array literal`` 的 P0 bug
正是从这条缝隙漏过去的（fake 全绿，CI 真实 PG 炸）。

本文件在真实 PG 上验证 migration runner 全链路：
    空库 → run_migrations()（含 baseline 检测/stamp 路径）
         → 版本记录 → 幂等重跑 → checksum 校验

使用独立 scratch 数据库（agent_platform_mig_selftest），不污染 HA 测试库；
连接池配置对齐生产 `db.init_pool`（autocommit + register_vector_async +
ensure_extensions，W-5），保证事务拓扑与 pgvector codec 与生产一致。
CI 由 pgvector/pgvector:pg16 service 提供 PG，本地无 PG 自动 skip（CI=true 时
FAIL，门禁策略单一来源见 conftest `pg_gate` fixture，W-3）。
"""

from __future__ import annotations

import os
import sys
from urllib.parse import urlsplit, urlunsplit

import pytest

pytestmark = pytest.mark.requires_pg

PG_URL = os.environ.get(
    "AGENT_PLATFORM_PG_URL",
    "postgresql://agent:agent_platform_dev@localhost:5433/agent_platform",
)
SCRATCH_DB = "agent_platform_mig_selftest"


def scratch_url_of(url: str) -> str:
    """把 PG URL 的库名替换为 scratch 库（其余连接参数/查询串原样保留）。

    纯函数（S-2）：用 urlsplit 解析，兼容查询串（?sslmode=require）、尾斜杠、
    driver 前缀（postgresql+psycopg://）等真实 URL 形态。
    """
    parts = urlsplit(url.strip())
    db = parts.path.strip("/")
    if not db or "/" in db:
        raise ValueError(f"PG URL 缺少或多段库名路径: {url!r}")
    return urlunsplit(parts._replace(path=f"/{SCRATCH_DB}"))


def test_scratch_url_of_handles_real_world_shapes():
    """S-2 回归：scratch URL 改写对真实 URL 形态健壮（纯函数，无需 PG）。"""
    cases = [
        "postgresql://agent:pwd@localhost:5432/db",
        "postgresql://agent:pwd@localhost:5432/db/",
        "postgresql://agent:pwd@localhost:5432/db?sslmode=require",
        "postgresql+psycopg://agent:pwd@host:5433/db",
    ]
    for url in cases:
        out = scratch_url_of(url)
        assert out.rsplit("/", 1)[-1].split("?")[0] == SCRATCH_DB, url
        if "?" in url:
            assert out.endswith(url.rsplit("?", 1)[1]), url
    with pytest.raises(ValueError):
        scratch_url_of("postgresql://agent:pwd@localhost:5432")


@pytest.fixture()
async def scratch_db(pg_gate):
    """创建一次性 scratch 数据库，测试结束销毁（清理置于 try/finally，W-6）。"""
    import psycopg

    if sys.platform == "win32":
        pg_gate(
            fail_reason="Windows CI 不支持 HA 测试（psycopg ProactorEventLoop），与 PG 可达性无关",
            skip_reason="Windows 本地默认跳过（psycopg ProactorEventLoop），由 Linux CI 覆盖",
        )

    created = False
    try:
        try:
            async with await psycopg.AsyncConnection.connect(PG_URL, autocommit=True) as conn:
                await conn.execute(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')
                await conn.execute(f'CREATE DATABASE "{SCRATCH_DB}"')
            created = True
        except Exception as exc:  # noqa: BLE001 —— 环境守卫：连接/建库失败归一门禁（CI=FAIL，本地=skip）
            pg_gate(
                fail_reason=(
                    f"CI 环境必须提供可用 PostgreSQL，migration 集成测试建库失败 "
                    f"[{type(exc).__name__}]：{exc}"
                ),
                skip_reason=(
                    f"本地无可用 PostgreSQL（migration 集成测试）"
                    f"[{type(exc).__name__}]：{exc}"
                ),
            )

        yield scratch_url_of(PG_URL)
    finally:
        if created:
            async with await psycopg.AsyncConnection.connect(PG_URL, autocommit=True) as conn:
                await conn.execute(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')


@pytest.fixture()
async def scratch_pool(scratch_db: str):
    """scratch 库连接池——**配置对齐生产 db.init_pool**（W-5）。

    - kwargs autocommit=True：与生产同事务拓扑（advisory lock 获取/释放边界等价）；
    - configure=register_vector_async：pgvector codec 注册（未来 migration 读写
      vector 列不失真）；
    - ensure_extensions 先行：生产在开池前启用扩展（db.py 记录的顺序约束），
      不依赖 baseline SQL 兜底。
    """
    from agent_runtime.db import ensure_extensions
    from pgvector.psycopg import register_vector_async
    from psycopg_pool import AsyncConnectionPool

    await ensure_extensions(scratch_db)
    pool = AsyncConnectionPool(
        conninfo=scratch_db,
        min_size=1,
        max_size=2,
        kwargs={"autocommit": True},
        configure=register_vector_async,
        open=False,
    )
    try:
        await pool.open(wait=True)
        yield pool
    finally:
        await pool.close()


async def test_fresh_db_full_migration_chain(scratch_pool):
    """空库 → run_migrations → 全版本落库；重跑幂等（applied=[]）。"""
    from agent_runtime.migrations.base import discover
    from agent_runtime.migrations.runner import get_current_version, run_migrations

    all_migrations = discover()
    assert all_migrations, "migrations 目录为空，测试前提不成立"
    max_version = max(m.version for m in all_migrations)

    # 首次运行：空库走 baseline 检测路径（曾因 tuple→ANY(%s) 在真实 PG 炸掉的代码）
    applied = await run_migrations(scratch_pool)
    applied_versions = [m.version for m in applied]
    assert applied_versions == [m.version for m in all_migrations], (
        f"应按序应用全部 migration: {applied_versions}"
    )
    assert await get_current_version(scratch_pool) == max_version

    # 幂等重跑：checksum 校验通过，无新增
    applied_again = await run_migrations(scratch_pool)
    assert applied_again == []
    assert await get_current_version(scratch_pool) == max_version


async def test_checksum_detects_drift_on_real_pg(scratch_pool):
    """真实 PG 上篡改已应用版本的 checksum → run_migrations 必须拒绝。"""
    from agent_runtime.migrations.runner import MigrationError, run_migrations

    await run_migrations(scratch_pool)  # 首次应用

    async with scratch_pool.connection() as conn:
        await conn.execute(
            "UPDATE schema_migrations SET checksum = 'tampered' WHERE version = "
            "(SELECT MIN(version) FROM schema_migrations)"
        )

    with pytest.raises(MigrationError, match="checksum mismatch"):
        await run_migrations(scratch_pool)


async def test_v6_upgrade_from_legacy_corpus_shape(scratch_pool):
    """R6 真集群复验拓出（2026-09-30）：v6 在存量库旧表形上不得崩 UndefinedColumn。

    旧基线形：chunks 的 workspace_id 由 v2 补，但 sql_ddl/sql_docs/sql_examples 在三表
    旧基线建表时无此列、增量链从未补 → v6 复合索引 (tenant_id, workspace_id) 在存量库
    升级路径必崩（集群实错：新库 baseline 自带该列故本地/CI 永不暴露）。
    修复：v6 自身对三表 ADD COLUMN IF NOT EXISTS workspace_id（对齐 001 现行定义）。
    本用例钉存量库升级语义本身，不经 runner（避开 baseline stamp 对全表集的依赖）。
    """
    from agent_runtime.migrations.base import discover

    v6 = next(m for m in discover() if m.version == 6)
    assert v6 is not None, "v6 不存在，测试前提不成立"
    sql = v6.read_up()

    async with scratch_pool.connection() as conn:
        # 构造 v2~v5 已过的存量库最小学表形：chunks 含 workspace_id（v2 已补），
        # 三张 sql_* 均无 workspace_id（缺陷复现点）；tenant_id 全缺（v6 职责）。
        await conn.execute(
            "CREATE TABLE chunks (id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL DEFAULT 'default')"
        )
        for t in ("sql_ddl", "sql_docs", "sql_examples"):
            await conn.execute(f"CREATE TABLE {t} (id TEXT PRIMARY KEY)")

        await conn.execute(sql)  # 修复前：三表复合索引 UndefinedColumn；修复后：全过

        for t in ("chunks", "sql_ddl", "sql_docs", "sql_examples"):
            row = await conn.execute(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s "
                "AND column_name IN ('workspace_id', 'tenant_id')",
                (t,),
            )
            assert (await row.fetchone())[0] == 2, f"{t} 应同时具备 workspace_id/tenant_id"

        await conn.execute(sql)  # 幂等重跑（全部 IF NOT EXISTS）


async def test_v11_upgrade_from_legacy_execution_shape(scratch_pool):
    """2026-10-10 真集群实跑拓出：存量库缺 4 列，/query 主链路必崩（v6 同族、成因不同）。

    成因不是「增量链漏了 ALTER」而是「baseline 从未执行」：集群库 schema_migrations 的
    1..10 applied_at 完全相同 ⇒ 走的是 runner._try_baseline_stamp() 的只记版本不执行 DDL
    路径；此后 baseline 的 ``CREATE TABLE IF NOT EXISTS`` 对已存在的旧形状表永久 no-op。
    ⇒ **重建镜像不会收敛该缺口**（运行 rev 的 001_baseline 已含 generation，线上表却没有）。

    钉的是产品代码路径本身而非列存在性：``PlannerRuntime.execution()`` 每次进入执行边界都
    acquire 租约（protocol.py:522 → durability_pg.py:219 的 INSERT 列含 generation），
    所以修复前用真 store 打一次就必须崩——这条断言同时是本用例的非空洞性证明。
    """
    import psycopg
    from agent_runtime.migrations.base import discover
    from agent_runtime.planner.durability_pg import PgExecutionOwnershipStore

    v11 = next(m for m in discover() if m.version == 11)
    assert v11 is not None, "v11 不存在，测试前提不成立"
    sql = v11.read_up()

    async with scratch_pool.connection() as conn:
        # 126 集群 information_schema 实测旧表形逐字复现（三张表各自的实际列集）
        await conn.execute(
            "CREATE TABLE execution_leases ("
            "execution_id TEXT PRIMARY KEY, owner TEXT NOT NULL, expires_at TIMESTAMPTZ NOT NULL)"
        )
        await conn.execute(
            "CREATE TABLE execution_checkpoints ("
            "execution_id TEXT PRIMARY KEY, completed JSONB NOT NULL DEFAULT '{}', "
            "updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
            "resumable BOOLEAN NOT NULL DEFAULT FALSE, version BIGINT NOT NULL DEFAULT 0)"
        )
        await conn.execute(
            "CREATE TABLE semantic_cache ("
            "id BIGSERIAL PRIMARY KEY, cache_key TEXT NOT NULL, question TEXT NOT NULL, "
            "answer TEXT NOT NULL, embedding vector(512), "
            "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )

    store = PgExecutionOwnershipStore(scratch_pool)

    # 修复前：产品代码路径必崩（集群实错原文：column "generation" of relation
    # "execution_leases" does not exist）
    with pytest.raises(psycopg.errors.UndefinedColumn, match="generation"):
        await store.acquire("exec-legacy", "replica-a:probe", 60.0)

    async with scratch_pool.connection() as conn:
        await conn.execute(sql)

    # 修复后：同一条产品代码路径必须真的走通
    assert await store.acquire("exec-legacy", "replica-a:probe", 60.0) is True
    assert await store.get_generation("exec-legacy") == 1
    assert await store.acquire("exec-legacy", "replica-a:probe", 60.0) is True
    # 同 owner 续租 generation 不变；takeover 才 +1（V3-1 fencing 语义）
    assert await store.get_generation("exec-legacy") == 1
    assert await store.heartbeat("exec-legacy", 60.0, owner="replica-a:probe") is True
    await store.release("exec-legacy", "replica-a:probe")

    async with scratch_pool.connection() as conn:
        # 列形状必须等于 001_baseline 现行声明（含 nullability / default 口径）
        shape = {
            ("execution_leases", "generation"): ("bigint", "NO", "1"),
            ("execution_checkpoints", "generation"): ("bigint", "YES", None),
            ("execution_checkpoints", "state_schema_version"): ("integer", "NO", "1"),
            ("semantic_cache", "tenant_id"): ("text", "NO", "''::text"),
        }
        for (table, col), (dtype, nullable, default) in shape.items():
            row = await conn.execute(
                "SELECT data_type, is_nullable, column_default FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s AND column_name = %s",
                (table, col),
            )
            rec = await row.fetchone()
            assert rec is not None, f"{table}.{col} 未被 v11 补上"
            assert rec[0] == dtype, (table, col, rec)
            assert rec[1] == nullable, (table, col, rec)
            got_default = rec[2] if rec[2] is not None else None
            if default is None:
                assert got_default is None, (table, col, rec)
            else:
                assert got_default and got_default.startswith(default), (table, col, rec)

        # semantic_cache 的租户谓词写入面（_cache_write 的列集含 tenant_id）
        await conn.execute(
            "INSERT INTO semantic_cache (cache_key, question, answer, embedding, tenant_id) "
            "VALUES (%s, %s, %s, %s::vector, %s)",
            ("k1", "q1", "a1", [0.0] * 512, "tenant-x"),
        )
        row = await conn.execute(
            "SELECT count(*) FROM semantic_cache WHERE tenant_id = %s", ("tenant-x",)
        )
        assert (await row.fetchone())[0] == 1

        await conn.execute(sql)  # 幂等重跑（全部 IF NOT EXISTS）
