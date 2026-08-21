"""P3-1 Trajectory 持久化验证。

覆盖：
- ExecutionContext.record_step 逐步记录（顺序 / latency / token delta / error）；
- PlannerRuntime.delegate 在 execution 边界内自动记录 step；
- execute_plan 执行后把 TrajectoryRecord 持久化到 InMemoryTrajectoryStore，
  按 execution_id 可查完整轨迹（skill / args / result / latency / tokens / error）与累计 tokens。
"""

from __future__ import annotations

import pytest

from agent_runtime.planner.execution_graph import execute_plan
from agent_runtime.planner.protocol import ExecutionContext, Plan, PlannerRuntime
from agent_runtime.trajectory import (
    InMemoryTrajectoryStore,
    TrajectoryRecord,
    TrajectoryStep,
)
from agent_runtime.trajectory.store import _coerce_record


class _FakeRegistry:
    async def execute(self, name, **kwargs):
        if name == "boom":
            raise RuntimeError("skill failed")
        return f"result-of-{name}"


def test_execution_context_record_step_order_and_tokens():
    ctx = ExecutionContext()
    ctx.tokens_used = 5
    ctx.record_step("a", {"x": 1}, result="ra", latency=0.1, tokens=5)
    ctx.record_step("b", {}, error="boom", latency=0.2, tokens=3)
    assert [s.name for s in ctx.steps] == ["a", "b"]
    assert ctx.steps[0].index == 0
    assert ctx.steps[1].index == 1
    assert ctx.steps[0].result == "ra"
    assert ctx.steps[1].error == "boom"
    assert ctx.steps[0].tokens == 5


@pytest.mark.asyncio
async def test_delegate_records_step_within_execution_scope():
    runtime = PlannerRuntime(registry=_FakeRegistry(), max_steps=20)
    async with runtime.execution():
        out = await runtime.delegate("search", q="weather")
        assert out == "result-of-search"
        assert len(runtime.context.steps) == 1
        step = runtime.context.steps[0]
        assert step.name == "search"
        assert step.args == {"q": "weather"}
        assert step.result == "result-of-search"
        assert step.latency >= 0


@pytest.mark.asyncio
async def test_delegate_records_step_on_error():
    runtime = PlannerRuntime(registry=_FakeRegistry(), max_steps=20)
    async with runtime.execution():
        with pytest.raises(RuntimeError):
            await runtime.delegate("boom")
        step = runtime.context.steps[0]
        assert step.name == "boom"
        assert step.error == "skill failed"


@pytest.mark.asyncio
async def test_execute_plan_persists_trajectory():
    store = InMemoryTrajectoryStore()
    runtime = PlannerRuntime(registry=_FakeRegistry(), trajectory_store=store, max_steps=20)
    plan = Plan(
        route="search",
        sub_query="q",
        notes={"question": "q", "workspace_id": "default", "session_id": "sess-1", "planner": "deterministic"},
    )

    events = [ev async for ev in execute_plan(plan, runtime)]
    assert any(e.type == "status" for e in events)

    # 按 execution_id 可查完整轨迹
    assert runtime.context is None  # 边界已退出
    record = runtime.last_trajectory
    assert isinstance(record, TrajectoryRecord)
    stored = await store.get(record.execution_id)
    assert stored is not None
    assert stored.session_id == "sess-1"
    assert stored.planner == "deterministic"
    assert len(stored.steps) == 1
    assert stored.steps[0].name == "search"
    assert stored.total_tokens == record.total_tokens
    assert stored.snapshot  # 含结构化 snapshot


@pytest.mark.asyncio
async def test_trajectory_store_list_by_session():
    store = InMemoryTrajectoryStore()
    r1 = TrajectoryRecord(session_id="s", planner="deterministic")
    r2 = TrajectoryRecord(session_id="s", planner="agentic")
    r3 = TrajectoryRecord(session_id="other")
    for r in (r1, r2, r3):
        await store.save(r)
    sess_s = await store.list_by_session("s")
    assert {x.execution_id for x in sess_s} == {r1.execution_id, r2.execution_id}


def test_coerce_record_roundtrip():
    rec = TrajectoryRecord(
        session_id="s",
        planner="deterministic",
        steps=[TrajectoryStep(name="a", args={"k": 1}, result="r", tokens=7)],
        total_tokens=7,
    )
    back = _coerce_record(rec.to_dict())
    assert back.session_id == "s"
    assert back.steps[0].name == "a"
    assert back.total_tokens == 7
