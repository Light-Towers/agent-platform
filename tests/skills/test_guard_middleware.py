# -*- coding: utf-8 -*-
"""WS-7：GuardMiddleware（超时隔离 + 失败降级）单测。

语义对齐 agent_core.tools.guarded_invoke：超时/异常 → fallback，绝不向上抛；
差异点：async-native（asyncio.wait_for 真正取消等待，不占线程池）。
"""

from __future__ import annotations

import asyncio

import pytest
from agent_runtime.skills.middleware import GuardMiddleware


async def _call_next_ok(name, kwargs):
    return {"evidence": ["ok"]}


async def _call_next_slow(name, kwargs):
    await asyncio.sleep(1.0)
    return {"evidence": ["late"]}


async def _call_next_boom(name, kwargs):
    raise RuntimeError("skill broken")


@pytest.mark.asyncio
async def test_guard_passes_through_on_success():
    mw = GuardMiddleware(timeout_s=1.0)
    assert await mw.around("search", {}, _call_next_ok) == {"evidence": ["ok"]}


@pytest.mark.asyncio
async def test_guard_timeout_returns_default_fallback():
    mw = GuardMiddleware(timeout_s=0.01)
    assert await mw.around("search", {}, _call_next_slow) == {}


@pytest.mark.asyncio
async def test_guard_timeout_returns_custom_fallback():
    mw = GuardMiddleware(timeout_s=0.01, fallback=["工具暂时不可用"])
    assert await mw.around("search", {}, _call_next_slow) == ["工具暂时不可用"]


@pytest.mark.asyncio
async def test_guard_exception_never_raises():
    mw = GuardMiddleware(timeout_s=1.0)
    assert await mw.around("search", {}, _call_next_boom) == {}


@pytest.mark.asyncio
async def test_guard_skill_names_filter():
    mw = GuardMiddleware(timeout_s=0.01, skill_names=("rag",))
    # 未命中的技能不受 guard 影响（慢调用也原样返回）
    assert await mw.around("search", {}, _call_next_slow) == {"evidence": ["late"]}
    # 命中的技能受超时约束
    assert await mw.around("rag", {}, _call_next_slow) == {}


@pytest.mark.asyncio
async def test_guard_in_registry_chain():
    """集成：挂入 SkillRegistry 洋葱链，execute 超时降级不抛错。"""
    from agent_runtime.skills.function import as_function_skill
    from agent_runtime.skills.registry import SkillRegistry

    async def slow_fn(**kwargs):
        await asyncio.sleep(1.0)
        return {"evidence": ["late"]}

    registry = SkillRegistry(middlewares=[GuardMiddleware(timeout_s=0.01)])
    registry.register(as_function_skill("slow", "慢技能", slow_fn))
    assert await registry.execute("slow") == {}
