"""真 PG 多副本故障接管集成测试（§20 阶段 1+2+3 验证，X：先验证后改 → 改后回归）。

仅当环境变量 AGENT_PLATFORM_PG_URL 存在时运行（无 PG / CI 无 docker 时跳过）。
默认指向本地已运行的 pgvector 容器：
  postgresql://agent:agent_platform_dev@localhost:5433/agent_platform

分层（2026-08-21 收敛决策）：
- Level 1 单副本 Durable Execution（当前 v2 必须 Green）：Test 1/2/3/5/6/7
    崩溃→重启→从 PG checkpoint resume，已完成节点 SKIP 不重跑
- Level 2 多副本 Execution HA（下一阶段，不阻塞 Level 1）：Test 4 / Test 8
    fencing / claim_stale / reaper 机制已落地验证，但暂缓接入运行时调度

运行：
    pytest -m "level1"   仅 Level 1（当前 v2 验收核心）
    pytest -m "level2"   Level 2（多副本 HA）
    不带 -m              全跑（需真 PG）

重点 Level 1 用例：
- Test 6/7: 新副本从 PG checkpoint resume，已完成节点 SKIP 不重跑
Level 2 用例（已落地但暂不作为当前 v2 阻塞项）：
- Test 4: 两副本真并发 claim_stale 同一 stale → winner-take-all fencing
- Test 8 (G4): stale owner 用过期 generation 回写 checkpoint → FencedWriteError
"""

import asyncio
import os

import pytest

# ---- 测试分层 marker（架构决策：Durable Execution 分 Level 1/2/3）----
# level1 = 单副本 crash recovery（当前 v2 必须 Green）
# level2 = 多副本 Execution HA（Lease/Heartbeat/Claim/Fencing，下一阶段，不阻塞当前 v2）
# 运行：pytest -m "level1" 仅跑 Level 1；pytest -m "level2" 跑 Level 2；不带 marker 全跑。
pytestmark = pytest.mark.level1  # 默认整文件归类，下面单测可覆盖

from agent_runtime.db import init_pool
from agent_runtime.planner.durability import (
    Checkpoint,
    FencedWriteError,
    InMemoryExecutionOwnershipStore,
)
from agent_runtime.planner.durability_pg import (
    PgCheckpointStore,
    PgExecutionOwnershipStore,
)
from agent_runtime.planner.execution_graph import ExecutionGraph, GraphNode
from agent_runtime.planner.protocol import PlannerRuntime

PG_URL = os.environ.get("AGENT_PLATFORM_PG_URL")
pytestmark = pytest.mark.skipif(
    not PG_URL, reason="需要真 PG：设置 AGENT_PLATFORM_PG_URL 后运行"
)

TABLES = ["execution_leases", "execution_checkpoints", "idempotency_keys"]


class _FakeRegistry:
    """最小 registry：delegate 返回确定性结果，供 _run_graph_in_place 驱动。"""

    def execute(self, name: str, **kwargs: object) -> str:
        return f"out:{name}"


@pytest.fixture
async def pool():
    # init_pool 复用模块级单例池（名称固定 'pool-1'），teardown 不 close 以免后续用例 PoolClosed。
    p = await init_pool(PG_URL)
    async with p.connection() as conn:
        for t in TABLES:
            await conn.execute(f"TRUNCATE {t} RESTART IDENTITY CASCADE")
    yield p


def _make_runtime(pool, ownership_store=None, checkpoint_store=None):
    return PlannerRuntime(
        registry=_FakeRegistry(),
        pool=pool,
        ownership_store=ownership_store or PgExecutionOwnershipStore(pool),
        checkpoint_store=checkpoint_store or PgCheckpointStore(pool),
    )


def _make_graph() -> ExecutionGraph:
    g = ExecutionGraph()
    g.add_node("a", "skill_a")
    g.add_node("b", "skill_b", input_refs={"x": "node:a"})
    g.add_node("c", "skill_c", input_refs={"x": "node:b"})
    return g


# ===== Test 1: lease 完整生命周期 =====
async def test_lease_lifecycle(pool):
    store = PgExecutionOwnershipStore(pool)
    granted, gen = await store.acquire("e1", "A", 10.0)
    assert granted is True and gen == 1
    assert await store.get_owner("e1") == "A"
    await store.heartbeat("e1", 20.0)
    assert await store.get_owner("e1") == "A"
    await store.release("e1", "A")
    assert await store.get_owner("e1") is None


# ===== Test 2: 正常 release 后 lease 消失 =====
async def test_release_clears_lease(pool):
    store = PgExecutionOwnershipStore(pool)
    await store.acquire("e2", "A", 10.0)
    await store.release("e2", "A")
    rows = await store.list_stale(9999999999.0)
    assert "e2" not in rows
    assert (await store.acquire("e2", "B", 10.0))[0] is True


# ===== Test 3: 模拟 kill -9（不 release）→ TTL 后变 stale =====
async def test_kill_minus_9_becomes_stale(pool):
    store = PgExecutionOwnershipStore(pool)
    await store.acquire("e3", "A", 0.05)
    assert await store.get_owner("e3") == "A"
    await asyncio.sleep(0.1)  # 不调用 release / heartbeat，模拟崩溃
    # 租约过期后 owner 视为 None，且出现在 stale 列表中
    assert await store.get_owner("e3") is None
    stale = await store.list_stale(0.0)
    assert "e3" in stale


# ===== Test 4 (核心): 两副本真并发 claim_stale 同一 stale → 唯一赢家 =====
    @pytest.mark.level2
async def test_concurrent_claim_fencing(pool):
    store = PgExecutionOwnershipStore(pool)
    cp = PgCheckpointStore(pool)
    # 制造一个已过期（kill -9）的 execution
    await store.acquire("shared", "A", 0.05)
    await cp.save(Checkpoint("shared", {"node1": "r1"}, graph_id="g1", graph_version="v1"))
    await asyncio.sleep(0.1)

    # 两个副本（B1 / B2）真并发触发 claim
    r1, r2 = await asyncio.gather(
        store.claim_stale("B1", 10.0),
        store.claim_stale("B2", 10.0),
    )
    claimed = dict(r1) | dict(r2)  # execution_id -> generation
    # winner-take-all：shared 只应出现在一个副本的认领结果里
    assert "shared" in claimed, f"shared 未被任何副本认领: {claimed}"
    winners = [who for who, res in (("B1", r1), ("B2", r2)) if any(e == "shared" for e, _ in res)]
    assert len(winners) == 1, f"FENCING 失败：多个副本认领同一 execution: {winners}"
    # 且 PG 端 owner 是单一赢家，不是 NULL
    owner = await store.get_owner("shared")
    assert owner in ("B1", "B2"), f"owner 非单一赢家: {owner}"


# ===== Test 5: checkpoint 写入真 PG（含版本字段）=====
async def test_checkpoint_persist_pg(pool):
    cp = PgCheckpointStore(pool)
    await cp.save(Checkpoint("e5", {"n1": "v1"}, graph_id="g1", graph_version="v1", checkpoint_version=1))
    loaded = await cp.load("e5")
    assert loaded is not None
    assert loaded.completed == {"n1": "v1"}
    assert loaded.graph_id == "g1" and loaded.graph_version == "v1"
    # 标记 resumable
    loaded.resumable = True
    await cp.save(loaded)
    assert (await cp.load("e5")).resumable is True


# ===== Test 6 + 7: 新副本从 PG checkpoint resume，已完成节点 SKIP 不重跑 =====
async def test_resume_skips_completed_nodes(pool):
    store = PgExecutionOwnershipStore(pool)
    cp = PgCheckpointStore(pool)

    # 模拟 A 副本：短 ttl 获得 ownership（崩溃后 lease 残留且过期），并已完成全部节点落盘
    await store.acquire("e6", "A", 0.05)
    await cp.save(
        Checkpoint("e6", {"a": "r1", "b": "r2", "c": "r3"}, generation=1,
                   graph_id="g1", graph_version="v1")
    )
    await asyncio.sleep(0.1)  # A 崩溃，lease 过期

    # B 副本从 PG checkpoint 接管：runtime.resume 语义 API
    # （内部 claim → validate graph_version → execution → _run_graph_in_place，已完成节点 SKIP）
    rt2 = PlannerRuntime(
        registry=_FakeRegistry(),
        pool=pool,
        ownership_store=store,
        checkpoint_store=cp,
    )
    rt2.max_duration_seconds = 10.0
    resumed_events = [e async for e in rt2.resume("e6", _make_graph(), graph_id="g1", graph_version="v1")]
    assert any(e.type == "answer" for e in resumed_events), "resume 未产出 answer"

    # 关键断言（Test 7）：已完成节点不得重跑 —— checkpoint 复用，结果仍在
    loaded = await cp.load("e6")
    assert loaded is not None
    assert loaded.completed == {"a": "r1", "b": "r2", "c": "r3"}


# ===== Test 8 (G4): stale owner 用过期 generation 回写 checkpoint → FencedWriteError =====
    @pytest.mark.level2
async def test_stale_owner_fenced_on_checkpoint_write(pool):
    store = PgExecutionOwnershipStore(pool)
    cp = PgCheckpointStore(pool)

    # A 获得 ownership（短 ttl，模拟崩溃后过期）→ generation=1
    await store.acquire("e8", "A", 0.05)
    await cp.save(Checkpoint("e8", {"a": "r1"}, generation=1))
    await asyncio.sleep(0.1)  # A 崩溃，lease 过期

    # B 认领 stale（A 崩溃）→ generation 变为 2
    reclaimed = await store.claim_stale("B", 10.0)
    assert ("e8", 2) in [(e, g) for e, g in reclaimed], f"B 未认领 e8: {reclaimed}"

    # A 恢复后用过期 token (gen=1) 回写 checkpoint → 必须被 fencing
    with pytest.raises(FencedWriteError):
        await cp.save(Checkpoint("e8", {"a": "stale-r1", "b": "x"}, generation=1))

    # B 用最新 token (gen=2) 写则成功
    await cp.save(Checkpoint("e8", {"a": "r1", "b": "r2"}, generation=2))
    loaded = await cp.load("e8")
    assert loaded.completed == {"a": "r1", "b": "r2"}
