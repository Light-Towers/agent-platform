"""Execution ownership + stale recovery（§11，纯逻辑半程，可单测）测试。"""

from __future__ import annotations

import time

from agent_runtime.planner.durability import (
    Checkpoint,
    InMemoryCheckpointStore,
    InMemoryExecutionOwnershipStore,
    reap_stale_executions,
)


async def test_ownership_acquire_rejects_active():
    store = InMemoryExecutionOwnershipStore()
    assert await store.acquire("e1", "ownerA", ttl_s=10.0)
    # 仍持有且未过期 → 拒绝（含自己续租语义由 heartbeat 承担）
    assert not await store.acquire("e1", "ownerB", ttl_s=10.0)
    assert await store.get_owner("e1") == "ownerA"


async def test_ownership_heartbeat_extends():
    store = InMemoryExecutionOwnershipStore()
    await store.acquire("e1", "ownerA", ttl_s=5.0)
    await store.heartbeat("e1", ttl_s=50.0)
    # heartbeat 顺延租约，应仍在持有
    assert await store.get_owner("e1") == "ownerA"
    await store.release("e1", "ownerA")
    assert await store.get_owner("e1") is None


async def test_reap_stale_releases_ownership_and_mark_checkpoint():
    own = InMemoryExecutionOwnershipStore()
    cp_store = InMemoryCheckpointStore()
    # 模拟一个已拿到所有权但租约过期的执行
    await own.acquire("e1", "ownerA", ttl_s=1.0)
    await cp_store.save(Checkpoint("e1", completed={"n1": {"x": 1}}))

    stale_now = time.monotonic() + 100.0  # 远超租约
    reclaimed = await reap_stale_executions(
        own, cp_store, now=stale_now
    )
    assert reclaimed == ["e1"]
    # 所有权已释放（可被其他副本/同 execution_id resume 接管）
    assert await own.get_owner("e1") is None
    # checkpoint 仍在，resume 路径可继续
    cp = await cp_store.load("e1")
    assert cp is not None and cp.completed == {"n1": {"x": 1}}


async def test_reap_stale_invokes_callback():
    own = InMemoryExecutionOwnershipStore()
    await own.acquire("e1", "ownerA", ttl_s=0.0)
    seen = []

    async def _on(eid):
        seen.append(eid)

    await reap_stale_executions(own, None, now=time.monotonic() + 10, on_stale=_on)
    assert seen == ["e1"]
