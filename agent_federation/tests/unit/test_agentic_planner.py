"""AgenticPlanner 单元测试（Plan-F Phase 2）。

覆盖：plan() 协议占位（route=agentic + sub_query 透传）、
execute() 包装 _execute_agent_core（route+answer 事件）、执行异常降级（error+空 answer）。
"""

from __future__ import annotations

import pytest

from agent_runtime.planner.protocol import PlannerContext, PlannerRuntime
from agent_federation.planners.agentic import AgenticPlanner


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
