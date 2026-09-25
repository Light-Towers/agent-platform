"""L3 真实 PostgreSQL migration 集成测试（P1-1 审计修复，2026-09-25）。

定位原则：**不让 L1 冒充 L3**。`test_schema_migrations.py` 的 FakeConnection 只
记录 SQL 字符串，不经过 psycopg → PostgreSQL 的真实参数适配——tuple 传
``ANY(%s)`` 被适配为 record 导致真实 PG 报 ``malformed array literal`` 的 P0 bug
正是从这条缝隙漏过去的（fake 全绿，CI 真实 PG 炸）。

本文件在真实 PG 上验证 migration runner 全链路：
    空库 → run_migrations()（含 baseline 检测/stamp 路径）
         → 版本记录 → 幂等重跑 → checksum 校验

使用独立 scratch 数据库（agent_platform_mig_selftest），不污染 HA 测试库；
CI 由 pgvector/pgvector:pg16 service 提供 PG，本地无 PG 自动 skip（CI=true 时 FAIL，
语义与 conftest 一致）。
"""

from __future__ import annotations

import os
import sys

import pytest

pytestmark = pytest.mark.requires_pg

PG_URL = os.environ.get(
    "AGENT_PLATFORM_PG_URL",
    "postgresql://agent:agent_platform_dev@localhost:5433/agent_platform",
)
SCRATCH_DB = "agent_platform_mig_selftest"

_IN_CI = os.environ.get("CI", "").strip().lower() in {"true", "1"}


def _skip_or_fail(reason: str) -> None:
    """本地无 PG → skip；CI 环境必须真实执行 → fail（与 tests/ha/conftest.py 一致）。"""
    if _IN_CI:
        pytest.fail(f"CI 环境必须提供可用 PostgreSQL，migration 集成测试前置失败：{reason}")
    pytest.skip(reason)


def _scratch_url() -> str:
    """把 PG_URL 的库名替换为 scratch 库（其余连接参数保持一致）。"""
    base, _, db = PG_URL.rsplit("/", 1)
    return f"{base}/{SCRATCH_DB}"


@pytest.fixture()
async def scratch_db():
    """创建一次性 scratch 数据库，测试结束销毁。"""
    if sys.platform == "win32" and not _IN_CI:
        pytest.skip("Windows 本地默认跳过（psycopg ProactorEventLoop），由 Linux CI 覆盖")

    import psycopg

    try:
        async with await psycopg.AsyncConnection.connect(PG_URL, autocommit=True) as conn:
            await conn.execute(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')
            await conn.execute(f'CREATE DATABASE "{SCRATCH_DB}"')
    except Exception as exc:  # noqa: BLE001 —— 环境守卫：任何连接/建库失败都归一为 skip（CI 为 fail）
        _skip_or_fail(repr(exc))

    yield _scratch_url()

    async with await psycopg.AsyncConnection.connect(PG_URL, autocommit=True) as conn:
        await conn.execute(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')


@pytest.fixture()
async def scratch_pool(scratch_db: str):
    """scratch 库的独立连接池（不走 _db.init_pool 单例，避免污染其他测试）。"""
    from psycopg_pool import AsyncConnectionPool

    pool = AsyncConnectionPool(conninfo=scratch_db, min_size=1, max_size=2, open=False)
    await pool.open(wait=True)
    yield pool
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
