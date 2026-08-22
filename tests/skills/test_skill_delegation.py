"""Skill Delegation API + ExecutionContext 落地测试（Plan-F 组合治理）。

覆盖：delegate 在/不在 execution 边界内的行为、步数累计、循环检测、深度上限、
ExecutionContext 真正生效（context 属性 / call_stack / step_count）。
"""

from __future__ import annotations

import pytest
from agent_runtime.planner.protocol import (
    ExecutionContext,
    PlannerRuntime,
    SkillCompositionError,
)


class _RecordingRegistry:
    """记录调用的注册表替身。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(self, name: str, **kwargs):
        self.calls.append(name)
        return f"result:{name}"


def _runtime(**kwargs) -> PlannerRuntime:
    return PlannerRuntime(registry=_RecordingRegistry(), llm=None, pool=None, **kwargs)


# ---------- delegate 边界回退 ----------


@pytest.mark.asyncio
async def test_delegate_outside_execution_fallback():
    """不在 execution 边界内时直接执行不护栏（deterministic 静态 DAG 兼容）。"""
    rt = _runtime()
    result = await rt.delegate("search", query="x")
    assert result == "result:search"
    assert rt.context is None


@pytest.mark.asyncio
async def test_delegate_within_execution_uses_guard():
    """在 execution 边界内时经 skill_guard，计入步数预算。"""
    rt = _runtime()
    async with rt.execution():
        await rt.delegate("search", query="x")
        assert rt._steps == 1
        assert rt._call_stack == []
    assert rt._steps == 0


# ---------- delegate 组合治理 ----------


@pytest.mark.asyncio
async def test_delegate_step_count_accumulates():
    rt = _runtime(max_steps=3)
    async with rt.execution():
        await rt.delegate("a")
        await rt.delegate("b")
        await rt.delegate("c")
        assert rt._steps == 3
        with pytest.raises(SkillCompositionError, match="步数"):
            await rt.delegate("d")


@pytest.mark.asyncio
async def test_delegate_cycle_detection():
    """delegate 嵌套调用同名 Skill 触发循环检测。"""
    reg = _RecordingRegistry()
    rt = PlannerRuntime(registry=reg)

    async def skill_a(**kwargs):
        return await rt.delegate("a")

    # 替换 registry.execute 让 a 递归调 delegate("a")
    async def recursive_a(name, **kwargs):
        if name == "a":
            return await rt.delegate("a")
        return "ok"

    reg.execute = recursive_a
    async with rt.execution():
        with pytest.raises(SkillCompositionError, match="循环"):
            await rt.delegate("a")


@pytest.mark.asyncio
async def test_delegate_depth_limit():
    rt = _runtime(max_skill_depth=1)
    async with rt.execution():
        async with rt.skill_guard("outer"):
            with pytest.raises(SkillCompositionError, match="深度"):
                async with rt.skill_guard("inner"):
                    pass


# ---------- ExecutionContext 落地 ----------


def test_execution_context_defaults():
    ctx = ExecutionContext()
    assert ctx.step_count == 0
    assert ctx.call_stack == []
    assert ctx.call_depth == 0
    assert ctx.max_steps == 20
    assert ctx.max_depth == 4


def test_execution_context_enter_exit():
    ctx = ExecutionContext(max_steps=10, max_depth=3)
    ctx.enter_skill("a")
    assert ctx.step_count == 1
    assert ctx.call_stack == ["a"]
    assert ctx.call_depth == 1
    ctx.enter_skill("b")
    assert ctx.step_count == 2
    assert ctx.call_depth == 2
    ctx.exit_skill()
    assert ctx.call_depth == 1
    assert ctx.call_stack == ["a"]
    ctx.exit_skill()
    assert ctx.call_depth == 0
    assert ctx.call_stack == []


def test_execution_context_cycle_detection():
    ctx = ExecutionContext()
    ctx.enter_skill("a")
    with pytest.raises(SkillCompositionError, match="循环"):
        ctx.enter_skill("a")


def test_execution_context_step_limit():
    ctx = ExecutionContext(max_steps=1)
    ctx.enter_skill("a")
    with pytest.raises(SkillCompositionError, match="步数"):
        ctx.enter_skill("b")


def test_execution_context_depth_limit():
    ctx = ExecutionContext(max_depth=1)
    ctx.enter_skill("a")
    with pytest.raises(SkillCompositionError, match="深度"):
        ctx.enter_skill("b")


# ---------- PlannerRuntime.context 属性 ----------


def test_context_property_none_outside():
    rt = _runtime()
    assert rt.context is None


@pytest.mark.asyncio
async def test_context_property_inside_execution():
    rt = _runtime()
    async with rt.execution():
        assert rt.context is not None
        assert isinstance(rt.context, ExecutionContext)
        assert rt.context.max_steps == 20
    assert rt.context is None


@pytest.mark.asyncio
async def test_context_reflects_skill_stack():
    rt = _runtime()
    async with rt.execution():
        async with rt.skill_guard("a"):
            assert rt.context.call_stack == ["a"]
            async with rt.skill_guard("b"):
                assert rt.context.call_stack == ["a", "b"]
        assert rt.context.call_stack == []
