"""Workflow Skill（Phase C）测试：compile_workflow 编译 + 经统一 Runtime 执行（含 $input/$node 映射）。"""

from __future__ import annotations

from agent_runtime.planner.execution_graph import execute_plan
from agent_runtime.planner.protocol import Plan, PlannerContext, PlannerRuntime
from agent_runtime.skills.registry import Skill, SkillKind, SkillRegistry
from agent_runtime.skills.workflow import (
    WorkflowEdge,
    WorkflowNode,
    WorkflowSpec,
    compile_workflow,
)


async def _fetch(**kwargs):
    return {"summary": f"searched:{kwargs.get('query')}"}


async def _analyze(**kwargs):
    return {"report": f"analyzed:{kwargs.get('data')}"}


def _base_registry() -> SkillRegistry:
    reg = SkillRegistry()
    reg.register(Skill("web_search", "联网搜索 web search", SkillKind.FUNCTION, _fetch))
    reg.register(Skill("analyze", "分析数据 analyze data", SkillKind.FUNCTION, _analyze))
    return reg


def _workflow_spec() -> WorkflowSpec:
    return WorkflowSpec(
        name="research_report",
        description="检索并分析生成报告 research report workflow",
        nodes=[
            WorkflowNode(id="n1", skill="web_search", inputs={"query": "$input.topic"}),
            WorkflowNode(id="n2", skill="analyze", inputs={"data": "$node.n1"}),
        ],
        edges=[WorkflowEdge(dependent="n2", dependency="n1")],
        input_schema={"type": "object", "properties": {"topic": {"type": "string"}}, "required": ["topic"]},
        output_schema={"type": "object"},
        output_node="n2",
    )


async def test_compile_and_execute_via_runtime():
    reg = _base_registry()
    wf = compile_workflow(_workflow_spec())
    assert wf.kind == SkillKind.WORKFLOW
    assert wf.metadata.get("kind") == "workflow"
    reg.register(wf)

    # 经 execute_plan 单 route delegate 调用（处于 execution 边界 → 复用上下文）
    runtime = PlannerRuntime(registry=reg)
    plan = Plan(mode="workflow", route="research_report", notes={"kwargs": {"topic": "北京天气"}})
    # execute_plan 的 else 分支从 notes["kwargs"] 取参并 delegate
    events = [ev async for ev in execute_plan(plan, runtime)]
    answer = next(e for e in events if e.type == "answer")
    # workflow 经 delegate 执行，结果被 execute_plan 包装为 str(text)
    assert "analyzed:" in str(answer.payload["text"])


async def test_workflow_nested_reuses_execution_context():
    reg = _base_registry()
    wf = compile_workflow(_workflow_spec(), registry=reg)
    reg.register(wf)

    runtime = PlannerRuntime(registry=reg, max_steps=20)
    # 手动进入 execution 边界，再经 delegate 调 workflow（模拟 execute_plan 的单 route 路径）
    async with runtime.execution():
        result = await runtime.delegate("research_report", topic="北京天气")
    assert result["report"] == "analyzed:{'summary': 'searched:北京天气'}"


async def test_workflow_independent_execution_creates_own_runtime():
    # 无运行边界、无 registry 注入时，独立执行应报错（明确而非静默）
    wf = compile_workflow(_workflow_spec())
    reg = _base_registry()
    reg.register(wf)
    runtime = PlannerRuntime(registry=reg)
    # 未进入 execution 边界，且 workflow 未绑定 registry → 应能自管 registry 执行
    async with runtime.execution():
        result = await runtime.delegate("research_report", topic="上海天气")
    assert result["report"] == "analyzed:{'summary': 'searched:上海天气'}"


async def test_workflow_discoverable_by_mode_selector():
    from agent_runtime.planner.mode_selector import ModeSelector

    reg = _base_registry()
    reg.register(compile_workflow(_workflow_spec()))
    sel = ModeSelector()
    ctx = PlannerContext(question="research report workflow", workspace_id="w", user_id="u")
    decision = await sel.select(ctx, reg)
    assert decision.mode.value == "workflow"
    assert decision.workflow_skill == "research_report"
