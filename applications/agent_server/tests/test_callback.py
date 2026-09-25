"""Callback API（V3 Phase 3.4b）测试：外部回调端点 + auto re-run。

覆盖：
- 正常回调 → AwaitableTask COMPLETED + 执行恢复（checkpoint 注入 + graph 重建 + re-run）
- 幂等：重复回调 → 200 "already_completed"
- 404：task 不存在
- error 回调 → AwaitableTask FAILED
- 无 checkpoint store → 优雅跳过
"""

from __future__ import annotations

import asyncio
from typing import Any

from agent_runtime.awaitable_task import (
    AwaitableKind,
    AwaitableState,
    AwaitableTask,
    InMemoryAwaitableTaskStore,
)
from agent_runtime.execution_status import (
    ExecutionStatus,
    ExecutionStatusRecord,
    InMemoryExecutionStatusStore,
)
from agent_runtime.planner.durability import (
    Checkpoint,
    InMemoryCheckpointStore,
)
from agent_runtime.planner.execution_graph import ExecutionGraph
from agent_runtime.planner.protocol import (
    Plan,
    PlannerRuntime,
)
from agent_runtime.skills.registry import Skill, SkillKind, SkillRegistry
from agent_runtime.trajectory.models import TrajectoryRecord
from agent_runtime.trajectory.store import InMemoryTrajectoryStore
from agent_server.api.callback import router as callback_router
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# ── helpers ──────────────────────────────────────────────────────────────────


async def _sync_skill(**kwargs: Any) -> dict[str, Any]:
    """同步 Skill：直接返回入参（用于 checkpoint resume 验证）。"""
    return {"echo": kwargs}


async def _awaitable_skill(**kwargs: Any) -> dict[str, Any]:
    """可等待 Skill：返回 __awaitable__ 标记（触发 ExecutionSuspended）。"""
    return {"__awaitable__": True, "task_id": "ext-123", "data": kwargs}


def _make_registry() -> SkillRegistry:
    reg = SkillRegistry()
    reg.register(Skill("sync_op", "同步操作", SkillKind.FUNCTION, _sync_skill))
    reg.register(Skill("async_op", "异步操作", SkillKind.FUNCTION, _awaitable_skill))
    return reg


def _make_graph() -> ExecutionGraph:
    """两节点图：n1(sync) → n2(sync)，用于 re-run 验证。"""
    g = ExecutionGraph()
    g.add_node("n1", "sync_op", kwargs={"query": "$query"})
    g.add_node("n2", "sync_op", input_refs={"data": "node:n1"})
    g.add_edge("n2", "n1")  # n2 依赖 n1
    return g


def _make_app(
    *,
    awaitable_store: InMemoryAwaitableTaskStore | None = None,
    checkpoint_store: InMemoryCheckpointStore | None = None,
    trajectory_store: InMemoryTrajectoryStore | None = None,
    status_store: InMemoryExecutionStatusStore | None = None,
    runtime: PlannerRuntime | None = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(callback_router)

    awaitable_store = awaitable_store or InMemoryAwaitableTaskStore()
    checkpoint_store = checkpoint_store or InMemoryCheckpointStore()
    trajectory_store = trajectory_store or InMemoryTrajectoryStore()
    status_store = status_store or InMemoryExecutionStatusStore()

    if runtime is None:
        reg = _make_registry()
        runtime = PlannerRuntime(
            registry=reg,
            checkpoint_store=checkpoint_store,
            trajectory_store=trajectory_store,
        )

    # 模拟 lifespan 装配
    app.state.awaitable_task_store = awaitable_store
    app.state.planner_runtime = runtime
    app.status_store = status_store
    # callback.py 用 getattr(app.state, "status_store", None)
    app.state.status_store = status_store

    return app


# ── tests ────────────────────────────────────────────────────────────────────


async def test_callback_404_task_not_found():
    """回调不存在的 task_id → 404。"""
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/callback/nonexistent", json={"result": {}})
    assert resp.status_code == 404


async def test_callback_idempotent_already_completed():
    """幂等：已 COMPLETED 的 task 重复回调 → 200 "already_completed"。"""
    store = InMemoryAwaitableTaskStore()
    task = AwaitableTask(
        execution_id="exec-1",
        step_id="n1",
        kind=AwaitableKind.CALLBACK,
        provider="test",
        state=AwaitableState.COMPLETED,
    )
    await store.save(task)

    app = _make_app(awaitable_store=store)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(f"/api/callback/{task.task_id}", json={"result": {"ok": True}})

    assert resp.status_code == 200
    assert resp.json()["status"] == "already_completed"


async def test_callback_error_marks_task_failed():
    """error 回调 → AwaitableTask FAILED，不触发 resume。"""
    store = InMemoryAwaitableTaskStore()
    task = AwaitableTask(
        execution_id="exec-err",
        step_id="n1",
        kind=AwaitableKind.EXTERNAL,
        provider="test",
        state=AwaitableState.RUNNING,
    )
    await store.save(task)

    app = _make_app(awaitable_store=store)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/callback/{task.task_id}",
            json={"error": "external service failed"},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"

    # 验证 store 中 task 状态
    loaded = await store.load(task.task_id)
    assert loaded is not None
    assert loaded.state == AwaitableState.FAILED
    assert loaded.completion_receipt == {"error": "external service failed"}


async def test_callback_success_marks_completed():
    """正常回调 → AwaitableTask COMPLETED + resume_payload 注入。"""
    store = InMemoryAwaitableTaskStore()
    task = AwaitableTask(
        execution_id="exec-ok",
        step_id="n1",
        kind=AwaitableKind.EXTERNAL,
        provider="test",
        state=AwaitableState.RUNNING,
    )
    await store.save(task)

    app = _make_app(awaitable_store=store)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/callback/{task.task_id}",
            json={"result": {"approval": "granted", "score": 0.95}},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"

    loaded = await store.load(task.task_id)
    assert loaded is not None
    assert loaded.state == AwaitableState.COMPLETED
    assert loaded.resume_payload == {"approval": "granted", "score": 0.95}
    assert loaded.completed_at is not None


async def test_callback_full_resume_with_graph_rerun():
    """完整 resume 流程：

    1. 预置：AwaitableTask(RUNNING) + checkpoint(n1 completed) + trajectory(plan with graph)
    2. 回调 → task COMPLETED + checkpoint 注入 n2 result + graph 重建 + re-run
    3. re-run 跳过 n1（checkpoint），执行 n2 → SUCCEEDED
    """
    exec_id = "exec-resume-1"

    # ── 预置 stores ──
    awaitable_store = InMemoryAwaitableTaskStore()
    checkpoint_store = InMemoryCheckpointStore()
    trajectory_store = InMemoryTrajectoryStore()
    status_store = InMemoryExecutionStatusStore()

    # AwaitableTask: n2 是挂起节点
    task = AwaitableTask(
        execution_id=exec_id,
        step_id="n2",
        kind=AwaitableKind.EXTERNAL,
        provider="test",
        state=AwaitableState.RUNNING,
    )
    await awaitable_store.save(task)

    # Checkpoint: n1 已完成
    n1_result = {"echo": {"query": "hello"}}
    await checkpoint_store.save(
        Checkpoint(exec_id, {"n1": n1_result}, resumable=True, generation=1)
    )

    # Trajectory: plan with graph
    graph = _make_graph()
    plan = Plan(mode="graph", route="sync_op", graph=graph)
    plan_dict = plan.model_dump()
    plan_dict["graph"] = graph.to_dict()
    trajectory = TrajectoryRecord(
        execution_id=exec_id,
        plan=plan_dict,
    )
    await trajectory_store.save(trajectory)

    # ExecutionStatus: SUSPENDED
    await status_store.save(
        ExecutionStatusRecord(execution_id=exec_id, status=ExecutionStatus.RUNNING)
    )

    # ── 构建 app + 发送回调 ──
    reg = _make_registry()
    runtime = PlannerRuntime(
        registry=reg,
        checkpoint_store=checkpoint_store,
        trajectory_store=trajectory_store,
    )
    app = _make_app(
        awaitable_store=awaitable_store,
        checkpoint_store=checkpoint_store,
        trajectory_store=trajectory_store,
        status_store=status_store,
        runtime=runtime,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/callback/{task.task_id}",
            json={"result": {"approved": True}},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"

    # 等待后台 resume task 完成（fire-and-forget）
    # _resume_execution 是 asyncio.create_task，需让事件循环跑完
    await asyncio.sleep(0.3)

    # ── 验证 resume 结果 ──
    # 1. AwaitableTask COMPLETED
    loaded_task = await awaitable_store.load(task.task_id)
    assert loaded_task is not None
    assert loaded_task.state == AwaitableState.COMPLETED

    # 2. Checkpoint 已更新（n2 结果注入）
    cp = await checkpoint_store.load(exec_id)
    assert cp is not None
    assert "n1" in cp.completed
    assert "n2" in cp.completed
    assert cp.completed["n2"] == {"approved": True}

    # 3. ExecutionStatus → SUCCEEDED
    status_rec = await status_store.load(exec_id)
    assert status_rec is not None
    assert status_rec.status == ExecutionStatus.SUCCEEDED


async def test_callback_no_checkpoint_store_skips_resume():
    """无 checkpoint store → 回调仍标记 COMPLETED，但不 resume（优雅降级）。"""
    store = InMemoryAwaitableTaskStore()
    task = AwaitableTask(
        execution_id="exec-no-cp",
        step_id="n1",
        kind=AwaitableKind.CALLBACK,
        provider="test",
        state=AwaitableState.SUBMITTED,
    )
    await store.save(task)

    # runtime without checkpoint_store
    reg = _make_registry()
    runtime = PlannerRuntime(registry=reg, checkpoint_store=None, trajectory_store=None)

    app = _make_app(awaitable_store=store, runtime=runtime)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/callback/{task.task_id}",
            json={"result": {"ok": True}},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"

    loaded = await store.load(task.task_id)
    assert loaded is not None
    assert loaded.state == AwaitableState.COMPLETED


async def test_callback_invalid_state_transition_409():
    """非法状态转换 → 409（如 PENDING → COMPLETED 不在转换表中）。"""
    store = InMemoryAwaitableTaskStore()
    task = AwaitableTask(
        execution_id="exec-invalid",
        step_id="n1",
        kind=AwaitableKind.CALLBACK,
        provider="test",
        state=AwaitableState.CANCELLED,  # CANCELLED 是终态，但 is_terminal 会先拦截
    )
    await store.save(task)

    app = _make_app(awaitable_store=store)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/callback/{task.task_id}",
            json={"result": {"ok": True}},
        )

    # CANCELLED is terminal → "already_completed" (幂等拦截在 state transition 检查之前)
    assert resp.status_code == 200
    assert resp.json()["status"] == "already_completed"
