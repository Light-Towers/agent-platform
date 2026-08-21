"""P5-1 TrajectoryFingerprint 验证。

覆盖：语义循环指纹（skill + 归一化 args）重复时拒绝继续（SkillCompositionError），
能拦「绕一圈回来同入参重复调用」；不同入参同名 Skill 不误伤；kwargs 键序无关。
"""

from __future__ import annotations

import pytest

from agent_runtime.planner.protocol import (
    ExecutionContext,
    PlannerRuntime,
    SkillCompositionError,
    _fingerprint,
)


class _FakeRegistry:
    async def execute(self, name, **kwargs):
        return f"result-of-{name}"


def test_fingerprint_kwargs_order_independent():
    assert _fingerprint("s", {"a": 1, "b": 2}) == _fingerprint("s", {"b": 2, "a": 1})


def test_fingerprint_differs_by_args():
    assert _fingerprint("s", {"q": "x"}) != _fingerprint("s", {"q": "y"})


def test_execution_context_blocks_duplicate_fingerprint():
    ctx = ExecutionContext()
    ctx.enter_skill("a", {"q": "x"})
    ctx.enter_skill("b", {"q": "x"})
    # A → B → A（同入参）应被语义指纹拦
    with pytest.raises(SkillCompositionError):
        ctx.enter_skill("a", {"q": "x"})


def test_execution_context_allows_different_args_same_name():
    ctx = ExecutionContext()
    ctx.enter_skill("a", {"q": "x"})
    ctx.exit_skill()
    # 同 Skill 不同入参（顺序调用，栈已退出）：不拦
    ctx.enter_skill("a", {"q": "y"})


def test_execution_context_allows_immediate_reentry_only_via_stack():
    # 即时重入仍由 call_stack 拦（即便指纹不同也会先被 name in call_stack 拦）
    ctx = ExecutionContext()
    ctx.enter_skill("a", {"q": "x"})
    with pytest.raises(SkillCompositionError):
        ctx.enter_skill("a", {"q": "z"})  # 同名即时重入：call_stack 先拦


@pytest.mark.asyncio
async def test_delegate_blocks_semantic_loop():
    runtime = PlannerRuntime(registry=_FakeRegistry(), max_steps=20, max_skill_depth=8)

    async def run():
        async with runtime.execution():
            await runtime.delegate("search", q="weather")
            await runtime.delegate("rag", q="weather")
            # 与第一次同入参的 search：语义循环
            await runtime.delegate("search", q="weather")

    with pytest.raises(SkillCompositionError):
        await run()


@pytest.mark.asyncio
async def test_delegate_allows_distinct_args():
    runtime = PlannerRuntime(registry=_FakeRegistry(), max_steps=20, max_skill_depth=8)
    async with runtime.execution():
        await runtime.delegate("search", q="weather")
        await runtime.delegate("search", q="news")  # 不同入参：允许
    assert runtime.context is None
