"""PlannerRuntime skill_guard 边界测试：步数/循环/深度护栏。"""

from __future__ import annotations

import pytest

from agent_runtime.planner.protocol import PlannerRuntime, SkillCompositionError
from agent_runtime.skills.function import as_function_skill
from agent_runtime.skills.registry import SkillRegistry


def _make_runtime(max_steps=20, max_depth=4) -> PlannerRuntime:
    reg = SkillRegistry()

    async def search(query):
        return f"result:{query}"

    async def analyze(text):
        return f"analyzed:{text}"

    async def summarize(text):
        return f"summarized:{text}"

    reg.register(as_function_skill("search", "搜索", search))
    reg.register(as_function_skill("analyze", "分析", analyze))
    reg.register(as_function_skill("summarize", "总结", summarize))
    return PlannerRuntime(reg, max_steps=max_steps, max_skill_depth=max_depth)


@pytest.mark.asyncio
async def test_skill_guard_requires_execution_context():
    runtime = _make_runtime()
    with pytest.raises(SkillCompositionError, match="execution"):
        async with runtime.skill_guard("search"):
            pass


@pytest.mark.asyncio
async def test_delegate_outside_execution_direct_execute():
    runtime = _make_runtime()
    result = await runtime.delegate("search", query="test")
    assert result == "result:test"


@pytest.mark.asyncio
async def test_delegate_inside_execution_with_guard():
    runtime = _make_runtime()
    async with runtime.execution():
        result = await runtime.delegate("search", query="test")
    assert result == "result:test"


@pytest.mark.asyncio
async def test_skill_guard_step_limit():
    runtime = _make_runtime(max_steps=3)
    async with runtime.execution():
        await runtime.delegate("search", query="q1")
        await runtime.delegate("search", query="q2")
        await runtime.delegate("search", query="q3")
        with pytest.raises(SkillCompositionError, match="步数"):
            await runtime.delegate("search", query="q4")


@pytest.mark.asyncio
async def test_skill_guard_depth_limit():
    runtime = _make_runtime(max_depth=2)
    async with runtime.execution():
        async with runtime.skill_guard("search"):
            async with runtime.skill_guard("analyze"):
                with pytest.raises(SkillCompositionError, match="深度"):
                    async with runtime.skill_guard("summarize"):
                        pass


@pytest.mark.asyncio
async def test_skill_guard_loop_detection():
    runtime = _make_runtime()
    async with runtime.execution():
        async with runtime.skill_guard("search"):
            with pytest.raises(SkillCompositionError, match="循环"):
                async with runtime.skill_guard("search"):
                    pass


@pytest.mark.asyncio
async def test_delegate_records_steps():
    runtime = _make_runtime()
    async with runtime.execution():
        await runtime.delegate("search", query="q1")
        await runtime.delegate("analyze", text="t1")
        ctx = runtime.context
        assert ctx is not None
        assert len(ctx.steps) == 2
