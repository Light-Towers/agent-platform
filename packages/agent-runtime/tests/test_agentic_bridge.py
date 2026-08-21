"""Agentic Runtime 收口（Phase D）测试：tool discovery→SkillRegistry；tool call→delegate 受治理；
subagent 作为 Agent Skill 经统一 Runtime 执行（架构验收 #4：不绕过 Skill Runtime）。"""

from __future__ import annotations

from agent_runtime.planner.agentic_bridge import (
    AgenticRuntimeBridge,
    RuntimeToolCaller,
    discover_agent_tools,
)
from agent_runtime.planner.protocol import PlannerRuntime
from agent_runtime.skills.registry import (
    Skill,
    SkillKind,
    SkillNotFoundError,
    SkillRegistry,
)


async def _search(**kwargs):
    return {"hits": [kwargs.get("query")]}


async def _analyze(**kwargs):
    return {"result": kwargs.get("data")}


def _registry() -> SkillRegistry:
    reg = SkillRegistry()
    reg.register(Skill("web_search", "联网搜索 web search", SkillKind.FUNCTION, _search))
    reg.register(Skill("analyze", "分析数据 analyze data", SkillKind.FUNCTION, _analyze))
    return reg


async def test_discover_agent_tools_from_registry():
    tools = discover_agent_tools(_registry(), "搜索 分析", top_k=10)
    names = {t["function"]["name"] for t in tools}
    assert names == {"web_search", "analyze"}


async def test_tool_call_routes_through_runtime_delegate():
    reg = _registry()
    runtime = PlannerRuntime(registry=reg, max_steps=20)
    caller = RuntimeToolCaller(runtime)
    async with runtime.execution():
        result = await caller.call("web_search", {"query": "北京"})
        # 经 delegate 执行，受组合治理：步数已计入
        assert result == {"hits": ["北京"]}
        assert runtime.context is not None and runtime.context.step_count == 1
        # 未注册能力被拒绝（不绕过 Runtime）
        try:
            await caller.call("rm_rf", {})
            assert False, "应拒绝未注册能力"
        except SkillNotFoundError:
            pass


async def test_bridge_simulated_agent_loop():
    reg = _registry()
    runtime = PlannerRuntime(registry=reg, max_steps=20)
    bridge = AgenticRuntimeBridge(runtime)

    # 模拟一个最小 agent loop：发现工具 → 决定调用 → 经 call_tool 执行（受治理）
    async def fake_agent_loop(query, tools, call_tool):
        assert any(t["function"]["name"] == "web_search" for t in tools)
        r1 = await call_tool("web_search", {"query": query})
        r2 = await call_tool("analyze", {"data": r1})
        return r2

    async with runtime.execution():
        answer = await fake_agent_loop("北京", bridge.discover("北京"), bridge.call_tool)
        # 两次 tool call 均经 delegate，步数累计（执行边界内断言）
        assert runtime.context is not None and runtime.context.step_count == 2
    assert answer == {"result": {"hits": ["北京"]}}


async def test_subagent_as_agent_skill_via_registry():
    # subagent 作为 Agent Skill 注册，并经统一 Runtime 执行（Phase D #3）
    async def _subagent_run(**kwargs):
        return {"answer": f"subagent:{kwargs.get('q')}"}

    reg = SkillRegistry()
    reg.register(Skill("kb_agent", "知识库子代理", SkillKind.AGENT, _subagent_run))
    runtime = PlannerRuntime(registry=reg, max_steps=20)
    async with runtime.execution():
        result = await runtime.delegate("kb_agent", q="天气")
    assert result == {"answer": "subagent:天气"}
