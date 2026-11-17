"""UnifiedPlanner（Phase A 收口）集成测试：graph / workflow 分发正确，不进入 deterministic 重路径。"""

from __future__ import annotations

from types import SimpleNamespace

from agent_runtime.capabilities.registry import Capability, CapabilityKind, CapabilityRegistry
from agent_runtime.planner.execution_graph import ExecutionGraph
from agent_runtime.planner.mode_selector import ExecutionMode, ModeSelector
from agent_runtime.planner.protocol import PlannerContext
from agent_server.planners.unified import UnifiedPlanner


async def _echo(**kwargs):
    return kwargs


def _registry() -> CapabilityRegistry:
    reg = CapabilityRegistry()
    reg.register(
        Capability(
            name="web_search",
            description="联网搜索网页信息 web search",
            kind=CapabilityKind.FUNCTION,
            executor=_echo,
            metadata={"kind": "function"},
        )
    )
    reg.register(
        Capability(
            name="analyze",
            description="分析结构化数据 analyze data",
            kind=CapabilityKind.FUNCTION,
            executor=_echo,
            metadata={"kind": "function"},
        )
    )
    reg.register(
        Capability(
            name="report_workflow",
            description="生成财务周报 report workflow",
            kind=CapabilityKind.FUNCTION,
            executor=_echo,
            metadata={"kind": "workflow"},
        )
    )
    return reg


def _ctx(q: str) -> PlannerContext:
    return PlannerContext(question=q, workspace_id="w", user_id="u")


async def test_unified_force_graph():
    settings = SimpleNamespace(planner="graph")
    planner = UnifiedPlanner(settings, _registry())  # type: ignore[arg-type]
    plan = await planner.plan(_ctx("搜索并分析 北京 天气 数据"))
    assert plan.mode == "graph"
    assert isinstance(plan.graph, ExecutionGraph)
    assert plan.execution_mode == ExecutionMode.GRAPH.value


async def test_unified_auto_workflow():
    settings = SimpleNamespace(planner="auto")
    planner = UnifiedPlanner(settings, _registry())  # type: ignore[arg-type]
    plan = await planner.plan(_ctx("生成财务周报"))
    assert plan.mode == "workflow"
    assert plan.route == "report_workflow"
    assert plan.execution_mode == ExecutionMode.WORKFLOW.value


async def test_unified_auto_graph_multi_capability():
    settings = SimpleNamespace(planner="auto")
    selector = ModeSelector()
    planner = UnifiedPlanner(settings, _registry(), selector=selector)  # type: ignore[arg-type]
    plan = await planner.plan(_ctx("搜索并分析 北京 天气 数据"))
    assert plan.mode == "graph"
    assert plan.execution_mode == ExecutionMode.GRAPH.value
