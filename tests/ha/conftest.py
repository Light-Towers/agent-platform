"""§HA 测试基础设施：真 PostgreSQL 双副本验证。

设计要点（用户红线）：
- 必须用真实 PostgreSQL（SQLite 会给出"测试通过但生产失败"的假象）——测的是
  lease / transaction / row locking / checkpoint persistence / concurrent ownership。
- 通过 db.init_pool 建真实连接池（自动 ensure_schema 建表，含 side_effects / execution_events）。
- 用同一 PG pool 构造两个 PlannerRuntime（replica-A / replica-B）模拟双副本，
  checkpoint / lease / idempotency 均共享同一 PG 后端——这正是 Durable Execution 的持久化事实源。
"""

import os
import sys
import uuid

import pytest
import pytest_asyncio

PG_URL = os.environ.get(
    "AGENT_PLATFORM_PG_URL",
    "postgresql://agent:agent_platform_dev@localhost:5433/agent_platform",
)

# 门禁语义（P0 审计修复，2026-09-25）：CI 环境下 PG 不可用 = FAIL 而非 SKIP。
# 本 workflow 名为 agent-platform-ha——"HA 测试 skipped 但 green" 会让人误以为 HA 已验证。
# GitHub Actions / 任何设置了 CI=true 的环境必须提供真实 PG；本地开发保留 skip。
_IN_CI = any(
    os.environ.get(k, "").strip().lower() in {"true", "1"}
    for k in ("CI", "GITHUB_ACTIONS")
)

from agent_runtime import db as _db
from agent_runtime.planner.durability_pg import (
    PgCheckpointStore,
    PgExecutionOwnershipStore,
    PgIdempotencyStore,
    PgSideEffectStore,
)


def pytest_collection_modifyitems(config, items):
    """自动给 tests/ha 下所有测试打 requires_pg marker（无需逐个文件标注）。

    配合 pg_pool fixture 的「本地无 PG 即 skip / CI 无 PG 即 fail」语义。
    路径判断必须平台无关：Windows fspath 是反斜杠，硬编码 "tests/ha" 会导致
    本机 marker 永远打不上（-m requires_pg 全部 deselect、-m "not requires_pg"
    全部混入普通套件）——Linux CI 不受影响所以此前未暴露。
    """
    for item in items:
        if "tests/ha" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.requires_pg)


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture(scope="session")
async def pg_pool():
    """真实 PG 连接池（session 级，共享；自动建表含 side_effects / execution_events）。

    §HA：必须用真实 PostgreSQL（SQLite 会给出"测试通过但生产失败"的假象）。
    本地无 PG（Windows 开发机）或平台不可用时自动 skip；
    **CI 环境（CI=true）一律 FAIL**——PG service 已由 workflow 显式提供，
    init 失败属于真实故障，不得以 skip 掩盖（P0 审计修复）。
    """
    if sys.platform == "win32":
        if _IN_CI:
            pytest.fail("Windows CI 不支持 HA 测试（psycopg ProactorEventLoop），应使用 Linux runner；与 PG 可达性无关")
        pytest.skip("Windows 下 psycopg ProactorEventLoop 不可用，HA 测试需真实 PG（Linux CI 覆盖）")
    try:
        pool = await _db.init_pool(PG_URL)
    except Exception as exc:
        # 归因信息显式带异常类型（W-3）：区分 PG 不可达 / 事件循环 / 权限等根因
        kind = type(exc).__name__
        if _IN_CI:
            pytest.fail(f"CI 环境必须提供可用 PostgreSQL（{PG_URL}），init_pool 失败 [{kind}]：{exc}")
        pytest.skip(f"未检测到可用 PostgreSQL（{PG_URL}）[{kind}]：{exc} —— HA 测试需真实 PG，Linux CI 自动覆盖")
    if pool is None:
        if _IN_CI:
            pytest.fail(f"CI 环境 init_pool 返回 None（PG 未配置），禁止以 skip 掩盖：{PG_URL}")
        pytest.skip("init_pool 返回 None（无可用 PG），HA 测试需真实 PostgreSQL")
    # 清理历史 HA 审计数据，保证断言基线干净
    async with pool.connection() as conn:
        await conn.execute("TRUNCATE side_effects, execution_events, execution_checkpoints, execution_leases, idempotency_keys")
    yield pool
    await _db.close_pool()


@pytest.fixture(scope="session")
def pg_gate():
    """PG 可用性门禁策略的**单一来源**（W-3，2026-09-25）。

    HA 相关测试文件判定 PG 环境一律经本 fixture，禁止各自复制 _IN_CI /
    skip/fail 逻辑（此前 conftest 与 test_migrations_real_pg.py 两份复制已漂移，
    且宽 except 把 Windows 事件循环问题误诊为「缺 PG」）。归因信息由调用方
    拼入 fail/skip 文案（须带异常类型名）。
    """
    def _gate(*, fail_reason: str, skip_reason: str) -> None:
        if _IN_CI:
            pytest.fail(fail_reason)
        pytest.skip(skip_reason)

    return _gate


@pytest_asyncio.fixture
async def ha_stores(pg_pool):
    """构造共享 PG 后端的 HA stores（副本 A/B 共用同一持久化事实源）。"""
    return {
        "checkpoint": PgCheckpointStore(pg_pool),
        "ownership": PgExecutionOwnershipStore(pg_pool),
        "idempotency": PgIdempotencyStore(pg_pool),
        "side_effect": PgSideEffectStore(pg_pool),
        "pool": pg_pool,
    }


def unique_execution_id(prefix: str = "HA") -> str:
    """每次实验生成可证明的 execution_id（HA-YYYYMMDD-<rand>）。"""
    from datetime import datetime
    stamp = datetime.now().strftime("%Y%m%d")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:8]}"


async def side_effect_counts(pool, execution_id: str) -> dict[str, int]:
    """查询某 execution 下各 effect 的实际副作用次数（effectively-once 证据）。"""
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT effect_key, count(*) FROM side_effects WHERE execution_id=%s "
            "GROUP BY effect_key ORDER BY effect_key",
            (execution_id,),
        )
        rows = await cur.fetchall()
    return {k: v for k, v in rows}


async def event_log(pool, execution_id: str) -> list[tuple]:
    """按时间序读取执行事件审计流（trajectory 连续性证据）。"""
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT created_at, replica, event, step_id FROM execution_events "
            "WHERE execution_id=%s ORDER BY created_at, id",
            (execution_id,),
        )
        rows = await cur.fetchall()
    return [(str(ts), replica, ev, step) for ts, replica, ev, step in rows]


async def checkpoint_completed(pool, execution_id: str) -> dict:
    """读取最终 checkpoint 的 completed 节点集合（psycopg 已将 jsonb 解析为 dict）。"""
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT completed FROM execution_checkpoints WHERE execution_id=%s",
            (execution_id,),
        )
        row = await cur.fetchone()
    return dict(row[0]) if row and row[0] else {}
