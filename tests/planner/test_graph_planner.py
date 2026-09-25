"""GraphPlanner 测试：Plan → ExecutionGraph → PolicyValidator → execute_graph 主链打通。"""

from __future__ import annotations

import pytest
from agent_runtime.planner.protocol import PlannerContext, PlannerRuntime
from agent_runtime.skills.function import as_function_skill
from agent_runtime.skills.registry import SkillRegistry
from agent_server.planners.graph import GraphPlanner


def _registry() -> SkillRegistry:
    reg = SkillRegistry()

    async def search(**kwargs):
        return f"search:{kwargs.get('query', '')}"

    async def analyze(**kwargs):
        return "analyze:done"

    reg.register(as_function_skill("search", "搜索 web 网页", search))
    reg.register(as_function_skill("analyze", "分析 数据", analyze))
    return reg


@pytest.mark.asyncio
async def test_graph_planner_plan_produces_graph():
    reg = _registry()
    planner = GraphPlanner(registry=reg)
    plan = await planner.plan(PlannerContext(question="搜索 web"))
    assert plan.mode == "graph"
    assert plan.graph is not None
    assert plan.graph.step_count() == 1


@pytest.mark.asyncio
async def test_graph_planner_execute_runs_full_chain():
    """完整链路：plan → execute → route/evidence/answer/status 事件。"""
    reg = _registry()
    planner = GraphPlanner(registry=reg)
    runtime = PlannerRuntime(registry=reg)

    plan = await planner.plan(PlannerContext(question="搜索 web"))
    events = [ev async for ev in planner.execute(plan, runtime)]

    types = [e.type for e in events]
    assert types[0] == "route"
    assert "evidence" in types
    assert types[-1] == "status"
    # snapshot 记录了 skill 输出
    status = events[-1]
    assert "search" in status.payload["snapshot"]["execution"]["outputs"]


@pytest.mark.asyncio
async def test_graph_planner_no_registry_falls_back():
    planner = GraphPlanner(registry=None)
    plan = await planner.plan(PlannerContext(question="test"))
    assert plan.mode == "deterministic"
    assert plan.graph is None


@pytest.mark.asyncio
async def test_graph_planner_no_candidates_falls_back():
    reg = SkillRegistry()
    planner = GraphPlanner(registry=reg)
    plan = await planner.plan(PlannerContext(question="test"))
    assert plan.mode == "deterministic"
    assert plan.route == "direct"
