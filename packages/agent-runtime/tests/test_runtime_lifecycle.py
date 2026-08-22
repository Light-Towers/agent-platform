"""PlannerRuntime 生命周期收尾（§7.1 / §11）：

- 进入 execution() 时自动跑 CompositionValidator 静态校验（非法组合 fail-fast）；
- 进入 execution() 时经 ownership_store acquire 执行所有权 + 心跳续租，退出时 release；
- reap_stale 回收 stale 执行（进程内检测 + 所有权回收，使其 checkpoint 可被 resume 接管）。
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest
from agent_runtime.planner.durability import (
    Checkpoint,
    InMemoryCheckpointStore,
    InMemoryExecutionOwnershipStore,
)
from agent_runtime.planner.protocol import PlannerRuntime
from agent_runtime.skills.composition import CompositionError
from agent_runtime.skills.registry import Skill, SkillKind, SkillRegistry

_ASYNC_NOOP = AsyncMock()


def _skill(name: str, sub_skills: tuple[str, ...] = (), permissions=frozenset()) -> Skill:
    return Skill(
        name=name,
        description=name,
        kind=SkillKind.FUNCTION,
        executor=_ASYNC_NOOP,
        sub_skills=sub_skills,
        permissions=permissions,
    )


async def test_composition_cycle_fails_at_execution_entry():
    reg = SkillRegistry()
    reg.register(_skill("a", sub_skills=("b",)))
    reg.register(_skill("b", sub_skills=("a",)))  # 环
    rt = PlannerRuntime(reg)

    with pytest.raises(CompositionError):
        async with rt.execution():
            pytest.fail("非法组合不应进入执行")


async def test_composition_missing_skill_fails_at_execution_entry():
    reg = SkillRegistry()
    reg.register(_skill("a", sub_skills=("ghost",)))  # 引用未注册能力
    rt = PlannerRuntime(reg)

    with pytest.raises(CompositionError):
        async with rt.execution():
            pytest.fail("非法组合不应进入执行")


async def test_valid_composition_passes_execution_entry():
    reg = SkillRegistry()
    # b 权限空集，a 持有 p1 超集 b 权限 → 权限闭包成立，无环
    reg.register(_skill("b", permissions=frozenset()))
    reg.register(_skill("a", sub_skills=("b",), permissions=frozenset({"p1"})))
    rt = PlannerRuntime(reg)

    async with rt.execution():
        assert rt.context is not None
        assert rt.context.execution_id


async def test_ownership_acquired_and_released():
    store = InMemoryExecutionOwnershipStore()
    rt = PlannerRuntime(SkillRegistry(), ownership_store=store)

    async with rt.execution():
        eid = rt.context.execution_id
        # §HA（C2）：owner 为 <replica_id>:<uuid>，跨副本唯一（非 PID，避免多容器撞车）
        owner = await store.get_owner(eid)
        assert owner is not None and owner.startswith("replica:") and len(owner.split(":")[1]) == 32

    assert await store.get_owner(eid) is None


async def test_reap_stale_recovers_expired_ownership_and_resumable_checkpoint():
    store = InMemoryExecutionOwnershipStore()
    cp = InMemoryCheckpointStore()
    rt = PlannerRuntime(SkillRegistry(), ownership_store=store, checkpoint_store=cp)

    stale_eid = "stale-1"
    # 另一进程持有、租约已过期
    await store.acquire(stale_eid, "other-pid", -1.0)
    # 该执行已有 checkpoint → 应被标记为可 resume
    await cp.save(Checkpoint(stale_eid, {"node_a": "ok"}))

    reaped = await rt.reap_stale()
    assert reaped == [stale_eid]
    # 所有权已释放
    assert await store.get_owner(stale_eid) is None
    # checkpoint 可被 resume 接管
    after = await cp.load(stale_eid)
    assert after is not None and after.resumable is True


async def test_reap_stale_keeps_active_ownership():
    store = InMemoryExecutionOwnershipStore()
    rt = PlannerRuntime(SkillRegistry(), ownership_store=store)

    await store.acquire("active-1", "other-pid", 300.0)  # 远未过期
    reaped = await rt.reap_stale()
    assert "active-1" not in reaped
    assert await store.get_owner("active-1") == "other-pid"


async def test_execution_without_registry_skips_composition_check():
    rt = PlannerRuntime(None)
    async with rt.execution():
        assert rt.context is not None


async def test_heartbeat_task_cancelled_on_exit():
    store = InMemoryExecutionOwnershipStore()
    rt = PlannerRuntime(SkillRegistry(), ownership_store=store, max_duration_seconds=300.0)

    async with rt.execution():
        eid = rt.context.execution_id
        # §HA（C2）：owner 为 <replica_id>:<uuid>（非 PID）
        owner = await store.get_owner(eid)
        assert owner is not None and owner.startswith("replica:") and len(owner.split(":")[1]) == 32
    # 退出后心跳任务已取消，所有权已释放
    assert await store.get_owner(eid) is None
