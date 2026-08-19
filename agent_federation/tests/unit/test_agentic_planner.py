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


@pytest.mark.asyncio
async def test_execute_bridges_monitor_events(monkeypatch):
    """execute 把 _execute_agent_core 运行期的 monitor 事件桥接为 evidence StreamEvent。"""
    from agent_core.monitor import monitor

    async def fake_core(task_query: str, workspace_id: str, main_agent=None) -> str:
        # 模拟运行期 sub-agent / 工具调用（经全局 monitor 发射）
        monitor.report_assistant("sub_agent_a", {"task": "search"})
        monitor.report_tool("vector_search", {"q": task_query})
        monitor.report_tool_outcome("vector_search", "success", detail="3 hits")
        return "上海共有 128 个用户。"

    import agent_federation.agent.main_agent as ma

    monkeypatch.setattr(ma, "_execute_agent_core", fake_core)

    planner = AgenticPlanner()
    plan = await planner.plan(PlannerContext(question="帮我查一下上海的用户", workspace_id="ws1"))
    runtime = PlannerRuntime(registry=None, pool=None)

    events = [ev async for ev in planner.execute(plan, runtime)]

    # route -> evidence* -> answer
    assert events[0].type == "route"
    assert events[-1].type == "answer"
    assert events[-1].payload["text"] == "上海共有 128 个用户。"

    evidence = [e for e in events if e.type == "evidence"]
    assert len(evidence) == 3, [e.payload.get("event") for e in evidence]
    ev_types = [e.payload["event"] for e in evidence]
    assert ev_types == ["assistant_call", "tool_start", "tool_outcome"]
    # 桥接保留原始信息（source + event + data 透传）
    assert evidence[0].payload["source"] == "federated_monitor"
    assert evidence[0].payload["data"]["assistant_name"] == "sub_agent_a"
    assert evidence[0].payload["data"]["args"]["task"] == "search"
    assert evidence[2].payload["data"]["detail"] == "3 hits"


@pytest.mark.asyncio
async def test_execute_bridge_cleans_subscription_on_error(monkeypatch):
    """执行异常时，monitor 订阅必须被注销，避免回调泄漏到后续请求。"""
    from agent_core.monitor import monitor

    async def boom(task_query: str, workspace_id: str, main_agent=None) -> str:
        monitor.report_assistant("sub_agent_a")
        raise RuntimeError("核心执行失败")

    import agent_federation.agent.main_agent as ma

    monkeypatch.setattr(ma, "_execute_agent_core", boom)

    planner = AgenticPlanner()
    plan = await planner.plan(PlannerContext(question="x", workspace_id="w"))
    runtime = PlannerRuntime(registry=None, pool=None)

    events = [ev async for ev in planner.execute(plan, runtime)]
    assert [e.type for e in events] == ["route", "error", "answer"]

    # 验证订阅已注销：再次用 monitor 发射，不应有遗留回调被触发
    leaked = []
    captured = {}

    def _probe(ev):
        leaked.append(ev)

    # 直接检查 monitor._callbacks 是否还有本测试的 handler 引用
    for etype in ("assistant_call", "tool_start", "tool_outcome", "session_created", "task_result", "circuit_state_change", "error"):
        for cb in list(monitor._callbacks.get(etype, [])):
            captured.setdefault(etype, []).append(cb)
    # 异常路径下所有桥接回调应已 off
    assert all(len(v) == 0 for v in captured.values()), captured
    assert leaked == []

