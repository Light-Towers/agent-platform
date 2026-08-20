"""execute_plan 测试（Plan-F 执行链打通）：Plan.graph 路径 + 单 route 路径 + ContextManager snapshot。"""

from __future__ import annotations

import asyncio

import pytest
from agent_runtime.planner.execution_graph import ExecutionGraph, execute_plan
from agent_runtime.planner.policy import PlanViolationError
from agent_runtime.planner.protocol import Plan, PlannerRuntime
from agent_runtime.skills.function import as_function_skill
from agent_runtime.skills.registry import SkillRegistry


def _registry() -> SkillRegistry:
    reg = SkillRegistry()

    async def search(**kwargs):
        return f"search:{kwargs.get('query', '')}"

    async def analyze(**kwargs):
        return "analyze:done"

    async def fail(**kwargs):
        raise RuntimeError("boom")

    async def slow(**kwargs):
        await asyncio.sleep(0.1)
        return "slow:done"

    reg.register(as_function_skill("search", "搜索", search))
    reg.register(as_function_skill("analyze", "分析", analyze))
    reg.register(as_function_skill("fail", "失败", fail))
    reg.register(as_function_skill("slow", "慢", slow))
    return reg


def _runtime(max_duration_seconds: float | None = None) -> PlannerRuntime:
    return PlannerRuntime(
        registry=_registry(), max_duration_seconds=max_duration_seconds
    )


# ---------- 单 route 路径 ----------


@pytest.mark.asyncio
async def test_execute_plan_single_route():
    plan = Plan(route="search", sub_query="test", notes={"kwargs": {"query": "x"}})
    events = [ev async for ev in execute_plan(plan, _runtime())]
    assert [e.type for e in events] == ["route", "evidence", "answer", "status"]
    assert events[0].payload["capability"] == "search"
    assert events[1].payload["result"] == "search:x"
    assert events[3].payload["snapshot"]["execution"]["outputs"]["search"] == "search:x"


# ---------- graph 路径 ----------


@pytest.mark.asyncio
async def test_execute_plan_graph_path():
    g = ExecutionGraph()
    g.add_node("a", "search", {"query": "x"})
    g.add_node("b", "analyze")
    g.add_edge("b", "a")
    plan = Plan(route="graph", graph=g)
    events = [ev async for ev in execute_plan(plan, _runtime())]
    types = [e.type for e in events]
    assert types[0] == "route"
    assert types[-1] == "status"
    assert "evidence" in types
    snapshot = events[-1].payload["snapshot"]
    assert "search" in snapshot["execution"]["outputs"]
    assert "analyze" in snapshot["execution"]["outputs"]


@pytest.mark.asyncio
async def test_execute_plan_graph_validation_rejected():
    """graph 有未注册能力时 execute_plan 经 PolicyValidator 拒绝。"""
    g = ExecutionGraph()
    g.add_node("a", "nonexistent")
    plan = Plan(route="graph", graph=g)
    with pytest.raises(PlanViolationError, match="未注册"):
        async for _ in execute_plan(plan, _runtime()):
            pass


@pytest.mark.asyncio
async def test_execute_plan_graph_error_isolation():
    """节点失败产出 error 事件，不阻断其他节点。"""
    g = ExecutionGraph()
    g.add_node("a", "search", {"query": "x"})
    g.add_node("b", "fail")
    plan = Plan(route="graph", graph=g)
    events = [ev async for ev in execute_plan(plan, _runtime())]
    error_events = [e for e in events if e.type == "error"]
    assert len(error_events) == 1
    assert error_events[0].payload["skill"] == "fail"
    assert "boom" in error_events[0].payload["error"]
    # search 仍成功
    evidence_events = [e for e in events if e.type == "evidence"]
    assert any(e.payload["skill"] == "search" for e in evidence_events)


# ---------- ContextManager snapshot ----------


@pytest.mark.asyncio
async def test_execute_plan_snapshot_records_errors():
    g = ExecutionGraph()
    g.add_node("a", "fail")
    plan = Plan(route="graph", graph=g)
    events = [ev async for ev in execute_plan(plan, _runtime())]
    status = next(e for e in events if e.type == "status")
    assert "fail" in status.payload["snapshot"]["execution"]["errors"]


# ---------- P1-1 / P1-2 接线回归 ----------


@pytest.mark.asyncio
async def test_execute_plan_deadline_aborts():
    """execution() 边界配置了 max_duration_seconds，跨层 deadline 超限应提前终止。"""
    g = ExecutionGraph()
    g.add_node("a", "slow")
    g.add_node("b", "search", {"query": "x"})
    g.add_edge("b", "a")  # b 依赖 a，a 先执行（慢），b 层检查 deadline 时必已超限
    plan = Plan(route="graph", graph=g)
    events = [ev async for ev in execute_plan(plan, _runtime(max_duration_seconds=0.01))]
    assert "answer" not in [e.type for e in events]
    error_events = [e for e in events if e.type == "error"]
    assert error_events, "应产出 deadline 超限 error 事件"
    assert "执行超时" in error_events[0].payload["error"]


@pytest.mark.asyncio
async def test_execute_plan_max_parallel_rejected():
    """同层节点数超 max_parallel 时，PolicyValidator 应拒绝（PlanViolationError）。"""
    g = ExecutionGraph()
    g.add_node("a", "search", {"query": "1"})
    g.add_node("b", "search", {"query": "2"})
    g.add_node("c", "search", {"query": "3"})
    plan = Plan(route="graph", graph=g)  # 三者同层
    with pytest.raises(PlanViolationError, match="并行度"):
        async for _ in execute_plan(plan, _runtime(), max_parallel=2):
            pass
