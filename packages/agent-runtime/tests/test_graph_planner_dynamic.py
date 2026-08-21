"""GraphPlanner（Phase B）集成测试：LLM 组合多 Skill DAG 并经 execute_plan 执行（含 input_refs 传递）。"""

from __future__ import annotations

import json

from agent_runtime.planner.execution_graph import execute_plan
from agent_runtime.planner.protocol import (
    PlannerContext,
    PlannerRuntime,
    StreamEvent,
)
from agent_runtime.skills.registry import Skill, SkillKind, SkillRegistry
from agent_server.planners.graph import GraphPlanner


async def _fetch(**kwargs):
    return {"summary": f"searched:{kwargs.get('query')}"}


async def _analyze(**kwargs):
    return {"report": f"analyzed:{kwargs.get('data')}"}


def _registry() -> SkillRegistry:
    reg = SkillRegistry()
    reg.register(Skill("web_search", "联网搜索 web search", SkillKind.FUNCTION, _fetch))
    reg.register(Skill("analyze", "分析数据 analyze data", SkillKind.FUNCTION, _analyze))
    return reg


class _FakeLLM:
    async def ainvoke(self, messages):
        payload = {
            "nodes": [
                {"id": "n1", "skill": "web_search", "inputs": {"query": "$query"}},
                {"id": "n2", "skill": "analyze", "inputs": {"data": "$node.n1"}},
            ],
            "edges": [{"dependent": "n2", "dependency": "n1"}],
        }
        return type("R", (), {"content": json.dumps(payload)})()


async def _collect(plan, runtime) -> list[StreamEvent]:
    return [ev async for ev in execute_plan(plan, runtime)]


async def test_graph_planner_compose_and_execute():
    reg = _registry()
    planner = GraphPlanner(registry=reg)
    ctx = PlannerContext(question="北京天气", workspace_id="w", user_id="u", llm=_FakeLLM())
    plan = await planner.plan(ctx)
    assert plan.mode == "graph"
    assert plan.graph is not None
    assert len(plan.graph.nodes) == 2
    assert plan.graph.nodes["n2"].input_refs["data"] == "node:n1"

    runtime = PlannerRuntime(registry=reg)
    events = await _collect(plan, runtime)
    answer = next(e for e in events if e.type == "answer")
    results = answer.payload["results"]
    # n2 的 analyze 收到的是 n1 的输出（input_refs 在运行时解析）
    assert results["n2"]["report"] == f"analyzed:{results['n1']}"


async def test_graph_planner_single_candidate_no_llm():
    reg = SkillRegistry()
    reg.register(Skill("only", "唯一能力", SkillKind.FUNCTION, _fetch))
    planner = GraphPlanner(registry=reg)
    # 无 LLM → 单节点
    ctx = PlannerContext(question="hi", workspace_id="w", user_id="u", llm=None)
    plan = await planner.plan(ctx)
    assert plan.graph is not None
    assert len(plan.graph.nodes) == 1
    # 单候选无 LLM 仍是单节点（非多 Skill 组合）
    assert list(plan.graph.nodes.values())[0].skill_name == "only"


async def test_graph_planner_compose_failure_falls_back():
    reg = _registry()

    class _BadLLM:
        async def ainvoke(self, messages):
            return type("R", (), {"content": "notjson"})()

    planner = GraphPlanner(registry=reg, max_compose_retries=0)
    ctx = PlannerContext(question="北京天气", workspace_id="w", user_id="u", llm=_BadLLM())
    plan = await planner.plan(ctx)
    # 组合失败 → 回退单节点（可治理，而非无限 loop）
    assert plan.graph is not None
    assert len(plan.graph.nodes) == 1
