"""AgenticPlanner 单元测试（Plan-F Phase 2/3）。

覆盖：plan() 协议占位（route=agentic + sub_query 透传）、
execute() 包装 _execute_agent_core（route+answer 事件）、执行异常降级（error+空 answer）、
arun() 经 skill_guard 治理复用 _execute_agent_core（返回答案）、
arun() 经 skill_guard 在步数超限时抛 SkillCompositionError。
"""

from __future__ import annotations

import os

# 确保 agent.llm 模块在 import main_agent 时成功初始化（无真实 key 时的测试桩）
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("OPENAI_BASE_URL", "http://localhost/v1")

import pytest
from agent_federation.planners.agentic import AgenticPlanner
from agent_runtime.planner.protocol import (
    PlannerContext,
    PlannerRuntime,
    SkillCompositionError,
)


@pytest.mark.asyncio
async def test_plan_protocol_placeholder():
    planner = AgenticPlanner()
    plan = await planner.plan(PlannerContext(question="帮我查一下上海的用户", workspace_id="ws1"))
    assert plan.route == "agentic"
    assert plan.sub_query == "帮我查一下上海的用户"
    assert plan.notes["workspace_id"] == "ws1"
    assert plan.notes["user_id"] == "default"


@pytest.mark.asyncio
async def test_execute_wraps_core(monkeypatch):
    async def fake_core(task_query: str, workspace_id: str, main_agent=None) -> str:
        assert task_query == "帮我查一下上海的用户"
        assert workspace_id == "ws1"
        return "上海共有 128 个用户。"

    import agent_federation.agent.main_agent as ma

    monkeypatch.setattr(ma, "_execute_agent_core", fake_core)

    planner = AgenticPlanner()
    plan = await planner.plan(PlannerContext(question="帮我查一下上海的用户", workspace_id="ws1"))
    runtime = PlannerRuntime(registry=None, pool=None)

    events = [ev async for ev in planner.execute(plan, runtime)]

    assert [e.type for e in events] == ["route", "answer"]
    assert events[0].payload["capability"] == "agentic"
    assert events[1].payload["text"] == "上海共有 128 个用户。"


@pytest.mark.asyncio
async def test_execute_degrades_on_error(monkeypatch):
    async def boom(task_query: str, workspace_id: str, main_agent=None) -> str:
        raise RuntimeError("核心执行失败")

    import agent_federation.agent.main_agent as ma

    monkeypatch.setattr(ma, "_execute_agent_core", boom)

    planner = AgenticPlanner()
    plan = await planner.plan(PlannerContext(question="x", workspace_id="w"))
    runtime = PlannerRuntime(registry=None, pool=None)

    events = [ev async for ev in planner.execute(plan, runtime)]

    assert [e.type for e in events] == ["route", "error", "answer"]
    assert "核心执行失败" in events[1].payload["error"]
    assert events[2].payload["text"] == ""


@pytest.mark.asyncio
async def test_arun_wraps_core_with_governance(monkeypatch):
    """arun 经 skill_guard 治理复用 _execute_agent_core，返回答案字符串。"""
    captured = {}

    async def fake_core(task_query: str, workspace_id: str, main_agent=None) -> str:
        captured["task_query"] = task_query
        captured["workspace_id"] = workspace_id
        captured["main_agent"] = main_agent
        return "上海共有 128 个用户。"

    import agent_federation.agent.main_agent as ma

    monkeypatch.setattr(ma, "_execute_agent_core", fake_core)

    planner = AgenticPlanner()
    runtime = PlannerRuntime(registry=None, pool=None)

    answer = await planner.arun("帮我查一下上海的用户", "ws1", runtime, main_agent="AGENT_X")

    assert answer == "上海共有 128 个用户。"
    assert captured["task_query"] == "帮我查一下上海的用户"
    assert captured["workspace_id"] == "ws1"
    assert captured["main_agent"] == "AGENT_X"
    # 组合治理已消费一次调用（_call_stack 已弹出）
    assert runtime._call_stack == []


@pytest.mark.asyncio
async def test_arun_raises_on_step_limit(monkeypatch):
    """arun 经 skill_guard 在步数超限时抛 SkillCompositionError。"""
    async def fake_core(task_query: str, workspace_id: str, main_agent=None) -> str:
        return "ok"

    import agent_federation.agent.main_agent as ma

    monkeypatch.setattr(ma, "_execute_agent_core", fake_core)

    planner = AgenticPlanner()
    # max_steps=1：第二次 arun 必超步数上限
    runtime = PlannerRuntime(registry=None, pool=None, max_steps=1)

    await planner.arun("q1", "ws1", runtime)
    with pytest.raises(SkillCompositionError):
        await planner.arun("q2", "ws1", runtime)

