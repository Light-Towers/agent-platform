"""Plan-F Phase 3：PlannerRuntime 组合治理（skill_guard）测试。

覆盖四护栏：正常嵌套退出后栈复位 / 循环调用检测（含跨层 A→B→A）/
嵌套深度上限 / 步数上限。deterministic 静态 DAG 天然无环，不使用该护栏。
"""

from __future__ import annotations

import pytest
from agent_runtime.planner.protocol import PlannerRuntime, SkillCompositionError


class _EmptyRegistry:
    async def execute(self, name, **kwargs):
        return None


def _runtime(**kwargs) -> PlannerRuntime:
    return PlannerRuntime(registry=_EmptyRegistry(), llm=None, pool=None, **kwargs)


@pytest.mark.asyncio
async def test_guard_allows_normal_composition_and_stack_reset():
    rt = _runtime()
    async with rt.skill_guard("a"):
        async with rt.skill_guard("b"):
            pass
    # 退出后栈复位，同名 Skill 可再次进入
    async with rt.skill_guard("a"):
        pass
    assert rt._call_stack == []


@pytest.mark.asyncio
async def test_guard_rejects_adjacent_cycle():
    rt = _runtime()
    async with rt.skill_guard("a"):
        with pytest.raises(SkillCompositionError, match="循环调用"):
            async with rt.skill_guard("a"):
                pass


@pytest.mark.asyncio
async def test_guard_rejects_cross_layer_cycle():
    """A → B → A 的跨层循环同样拦截（非仅相邻重复）。"""
    rt = _runtime()
    async with rt.skill_guard("a"):
        async with rt.skill_guard("b"):
            with pytest.raises(SkillCompositionError, match="循环调用"):
                async with rt.skill_guard("a"):
                    pass


@pytest.mark.asyncio
async def test_guard_rejects_depth_overflow():
    rt = _runtime(max_skill_depth=2)
    async with rt.skill_guard("a"):
        async with rt.skill_guard("b"):
            with pytest.raises(SkillCompositionError, match="深度"):
                async with rt.skill_guard("c"):
                    pass


@pytest.mark.asyncio
async def test_guard_rejects_step_overflow():
    """步数上限在单次执行内（同 task 链嵌套）累计并拦截。"""
    rt = _runtime(max_steps=2)
    async with rt.skill_guard("a"):
        async with rt.skill_guard("b"):
            with pytest.raises(SkillCompositionError, match="步数"):
                async with rt.skill_guard("c"):
                    pass


@pytest.mark.asyncio
async def test_guard_budget_resets_after_execution():
    """预算 per-request：执行退出后复位，不影响后续执行（架构审核 P0）。"""
    rt = _runtime(max_steps=1)
    # 单次执行：第一个 guard 消费预算，同执行内嵌套第二个必超
    async with rt.skill_guard("a"):
        with pytest.raises(SkillCompositionError, match="步数"):
            async with rt.skill_guard("b"):
                pass
    # 执行结束预算复位：后续新执行可正常进入
    async with rt.skill_guard("a"):
        pass
    assert rt._steps == 0
    assert rt._call_stack == []


@pytest.mark.asyncio
async def test_guard_defaults():
    rt = _runtime()
    assert rt.max_skill_depth == 4
    assert rt.max_steps == 20
