"""Mode Selector（Phase A）单元测试：force override / workflow 复用 / 启发式 / 不默认 agentic。"""

from __future__ import annotations

from agent_runtime.planner.mode_selector import (
    ExecutionMode,
    ModeSelector,
)
from agent_runtime.planner.protocol import PlannerContext
from agent_runtime.skills.registry import Skill, SkillKind, SkillRegistry


async def _echo(**kwargs):
    return kwargs


def _fn(name: str, description: str, kind: str) -> Skill:
    return Skill(
        name=name,
        description=description,
        kind=SkillKind.FUNCTION,
        executor=_echo,
        metadata={"kind": kind},
    )


def _registry() -> SkillRegistry:
    reg = SkillRegistry()
    reg.register(_fn("web_search", "联网搜索网页信息 web search", "function"))
    reg.register(_fn("analyze", "分析结构化数据 analyze data", "function"))
    reg.register(_fn("report_workflow", "生成财务周报 report workflow", "workflow"))
    return reg


def _ctx(q: str) -> PlannerContext:
    return PlannerContext(question=q, workspace_id="w", user_id="u")


async def test_force_mode_override():
    sel = ModeSelector(force_mode="graph")
    dec = await sel.select(_ctx("北京天气"), _registry())
    assert dec.mode == ExecutionMode.GRAPH
    assert dec.reason == "forced by PLANNER override"


async def test_workflow_reuse_priority():
    sel = ModeSelector()
    dec = await sel.select(_ctx("生成财务周报"), _registry())
    assert dec.mode == ExecutionMode.WORKFLOW
    assert dec.workflow_skill == "report_workflow"


async def test_heuristic_deterministic_single():
    sel = ModeSelector()
    dec = await sel.select(_ctx("联网搜索 北京天气"), _registry())
    assert dec.mode == ExecutionMode.DETERMINISTIC


async def test_heuristic_graph_multiple():
    sel = ModeSelector(graph_min_relevant=2)
    dec = await sel.select(_ctx("搜索并分析 北京 天气 数据"), _registry())
    assert dec.mode == ExecutionMode.GRAPH


async def test_agentic_not_default_without_classifier():
    sel = ModeSelector(agentic_enabled=True)
    dec = await sel.select(_ctx("随便聊聊"), _registry())
    # 无 classifier 时即使启用 agentic 也不应默认进入（doc §17：不要所有任务都 agentic）
    assert dec.mode != ExecutionMode.AGENTIC


async def test_classifier_proposal_downgraded_when_agentic_disabled():
    async def _cls(q, reg):
        return "agentic"

    sel = ModeSelector(classifier=_cls, agentic_enabled=False)
    dec = await sel.select(_ctx("探索未知问题"), _registry())
    assert dec.mode == ExecutionMode.GRAPH


async def test_classifier_agentic_when_enabled():
    async def _cls(q, reg):
        return "agentic"

    sel = ModeSelector(classifier=_cls, agentic_enabled=True)
    dec = await sel.select(_ctx("开放式探索任务"), _registry())
    assert dec.mode == ExecutionMode.AGENTIC
