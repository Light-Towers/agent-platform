"""§HA 测试基础设施：真 PostgreSQL 双副本验证。

设计要点（用户红线）：
- 必须用真实 PostgreSQL（SQLite 会给出"测试通过但生产失败"的假象）——测的是
  lease / transaction / row locking / checkpoint persistence / concurrent ownership。
- 通过 db.init_pool 建真实连接池（自动 ensure_schema 建表，含 side_effects / execution_events）。
- 用同一 PG pool 构造两个 PlannerRuntime（replica-A / replica-B）模拟双副本，
  checkpoint / lease / idempotency 均共享同一 PG 后端——这正是 Durable Execution 的持久化事实源。
"""

import os
import uuid

import pytest
import pytest_asyncio

PG_URL = os.environ.get(
    "AGENT_PLATFORM_PG_URL",
    "postgresql://agent:agent_platform_dev@localhost:5433/agent_platform",
)

from agent_runtime import db as _db
from agent_runtime.planner.durability_pg import (
    PgCheckpointStore,
    PgExecutionOwnershipStore,
    PgIdempotencyStore,
)


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture(scope="session")
async def pg_pool():
    """真实 PG 连接池（session 级，共享；自动建表含 side_effects / execution_events）。"""
    pool = await _db.init_pool(PG_URL)
    assert pool is not None, "DATABASE_URL 应可连接（真 PostgreSQL 才能验证 HA）"
    # 清理历史 HA 审计数据，保证断言基线干净
    async with pool.connection() as conn:
        await conn.execute("TRUNCATE side_effects, execution_events, execution_checkpoints, execution_leases, idempotency_keys")
    yield pool
    await _db.close_pool()


@pytest_asyncio.fixture
async def ha_stores(pg_pool):
    """构造共享 PG 后端的 HA stores（副本 A/B 共用同一持久化事实源）。"""
    return {
        "checkpoint": PgCheckpointStore(pg_pool),
        "ownership": PgExecutionOwnershipStore(pg_pool),
        "idempotency": PgIdempotencyStore(pg_pool),
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
