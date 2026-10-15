"""Human Task API（V3 补-1）测试：审批面 + 挂起状态映射。

覆盖三段链的**第三段（审批面）**与**第二段的落点（状态映射）**，与既有
``packages/agent-runtime/tests/test_human_task.py``（store/resolver 内部流转）、
``test_human_task_wiring.py``（protocol 分派 + graph kind 透传）分工互补：

- approve ⇒ task COMPLETED + resume_payload.decision=="approved"，且 ``WAITING_HUMAN → RUNNING``
  **真发生**（经 HTTP，不是手动 seed resolver——这条同时证明第二段接线不是死代码）；
- reject ⇒ task FAILED + 执行状态 FAILED；
- ``approver`` 恒为**服务端断言主体**：请求体里塞假 approver，落库 receipt 里不得出现它
  （防「客户端自报审计主体」回潮，见 plan-audit-operator-principal-2026-10-03）；
- list / get / 404 / 503（未装配）；
- ``_suspend_status``：human ⇒ WAITING_HUMAN，其余 ⇒ WAITING_EXTERNAL（回归锁）。
"""

from __future__ import annotations

import json

from agent_runtime.awaitable_task import (
    AwaitableKind,
    AwaitableState,
    InMemoryAwaitableTaskStore,
)
from agent_runtime.execution_status import (
    ExecutionStatus,
    ExecutionStatusRecord,
    InMemoryExecutionStatusStore,
)
from agent_runtime.human_task import (
    HumanTask,
    HumanTaskResolver,
    HumanTaskStore,
)
from agent_runtime.workspace_registry import server_tenant_id
from agent_server.api.human_task import router as human_task_router
from agent_server.api.query_router import _suspend_status
from agent_server.config import get_settings
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# ── helpers ──────────────────────────────────────────────────────────────────


def _expected_approver() -> str:
    """与 api/human_task._approver() 同式：服务端断言主体（测试里 ContextVar 未绑定）。"""
    return server_tenant_id(get_settings().default_tenant_id)


def _make_app(
    *,
    with_store: bool = True,
    with_resolver: bool = True,
    status_store: InMemoryExecutionStatusStore | None = None,
) -> tuple[FastAPI, InMemoryAwaitableTaskStore | None, InMemoryExecutionStatusStore | None]:
    """构建只挂 human_task_router 的最小 app，模拟 lifespan 装配。

    返回 (app, awaitable_store, status_store) 供断言直接查库。
    """
    app = FastAPI()
    app.include_router(human_task_router)

    awaitable_store = InMemoryAwaitableTaskStore()
    status_store = status_store or InMemoryExecutionStatusStore()
    human_store = HumanTaskStore(awaitable_store)

    if with_store:
        app.state.human_task_store = human_store
    if with_resolver:
        app.state.human_task_resolver = HumanTaskResolver(human_store, status_store=status_store)

    return app, (awaitable_store if with_store else None), status_store


async def _seed_human_task(
    app: FastAPI, execution_id: str, *, waiting_status: bool = True
) -> str:
    """经 app.state 的 HumanTaskStore 建一条 PENDING 人工任务；可选 seed WAITING_HUMAN 状态。"""
    store: HumanTaskStore = app.state.human_task_store
    task = HumanTask(
        execution_id=execution_id,
        step_id="approval",
        prompt="请审批此合同变更",
        options=["approve", "reject"],
        approver="manager_a",
        context={"contract_id": "C001"},
    )
    awaitable = await store.create(task)
    if waiting_status:
        resolver: HumanTaskResolver = app.state.human_task_resolver
        # resolver 持有同一个 status_store；直接经它写 WAITING_HUMAN 模拟挂起态
        assert resolver._status_store is not None
        await resolver._status_store.save(
            ExecutionStatusRecord(execution_id, ExecutionStatus.WAITING_HUMAN, generation=1)
        )
    return awaitable.task_id


async def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ── approve / reject ─────────────────────────────────────────────────────────


async def test_approve_completes_task_and_resumes_execution():
    """approve ⇒ task COMPLETED + resume_payload.decision=approved + WAITING_HUMAN→RUNNING。"""
    app, awaitable_store, status_store = _make_app()
    task_id = await _seed_human_task(app, "exec-1")

    async with await _client(app) as client:
        resp = await client.post(f"/api/human-tasks/{task_id}/approve", json={"comment": "同意"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "completed"
    assert body["decision"] == "approved"
    assert body["approver"] == _expected_approver()

    # task 落库 COMPLETED + resume_payload
    loaded = await awaitable_store.load(task_id)
    assert loaded.state is AwaitableState.COMPLETED
    assert loaded.resume_payload["decision"] == "approved"
    assert loaded.resume_payload["comment"] == "同意"

    # 第二段接线的证明：WAITING_HUMAN → RUNNING 真的发生（此前是死代码）
    rec = await status_store.load("exec-1")
    assert rec.status is ExecutionStatus.RUNNING


async def test_reject_fails_task_and_execution():
    """reject ⇒ task FAILED + 执行状态 FAILED。"""
    app, awaitable_store, status_store = _make_app()
    task_id = await _seed_human_task(app, "exec-2")

    async with await _client(app) as client:
        resp = await client.post(f"/api/human-tasks/{task_id}/reject", json={"comment": "金额超限"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "failed"
    assert body["decision"] == "rejected"

    loaded = await awaitable_store.load(task_id)
    assert loaded.state is AwaitableState.FAILED
    assert loaded.completion_receipt["decision"] == "rejected"

    rec = await status_store.load("exec-2")
    assert rec.status is ExecutionStatus.FAILED


async def test_approve_404_when_task_missing():
    """approve 不存在的 task → 404（resolver 抛 ValueError 被端点转 404）。"""
    app, _, _ = _make_app()
    async with await _client(app) as client:
        resp = await client.post("/api/human-tasks/nonexistent/approve", json={"comment": ""})
    assert resp.status_code == 404


# ── 审批主体：服务端断言，不接受客户端自报 ──────────────────────────────────


async def test_approver_is_server_asserted_not_client_supplied():
    """请求体塞假 approver → 落库 receipt 里不得出现它，approver 恒为服务端主体。

    这是 plan-audit-operator-principal 整改要消除的形状（客户端自报审计主体）的回潮锁。
    """
    app, awaitable_store, _ = _make_app()
    task_id = await _seed_human_task(app, "exec-3")

    async with await _client(app) as client:
        resp = await client.post(
            f"/api/human-tasks/{task_id}/approve",
            json={"approver": "evil_client", "comment": "looks legit"},
        )

    assert resp.status_code == 200
    assert resp.json()["approver"] == _expected_approver()

    loaded = await awaitable_store.load(task_id)
    receipt_blob = json.dumps(
        {"completion_receipt": loaded.completion_receipt, "resume_payload": loaded.resume_payload},
        ensure_ascii=False,
    )
    assert loaded.completion_receipt["approver"] == _expected_approver()
    assert "evil_client" not in receipt_blob


# ── list / get ───────────────────────────────────────────────────────────────


async def test_get_task_returns_view():
    app, _, _ = _make_app()
    task_id = await _seed_human_task(app, "exec-4", waiting_status=False)

    async with await _client(app) as client:
        resp = await client.get(f"/api/human-tasks/task/{task_id}")

    assert resp.status_code == 200
    view = resp.json()
    assert view["task_id"] == task_id
    assert view["execution_id"] == "exec-4"
    assert view["state"] == "pending"
    assert view["prompt"] == "请审批此合同变更"
    assert view["options"] == ["approve", "reject"]


async def test_get_task_404():
    app, _, _ = _make_app()
    async with await _client(app) as client:
        resp = await client.get("/api/human-tasks/task/nope")
    assert resp.status_code == 404


async def test_list_pending_only_returns_non_terminal_human_tasks():
    app, _, _ = _make_app()
    t1 = await _seed_human_task(app, "exec-5", waiting_status=False)
    t2 = await _seed_human_task(app, "exec-5", waiting_status=False)

    # t1 审批完成 → 不应再出现在 pending
    async with await _client(app) as client:
        await client.post(f"/api/human-tasks/{t1}/approve", json={"comment": ""})
        resp = await client.get("/api/human-tasks/exec-5")

    assert resp.status_code == 200
    body = resp.json()
    assert body["execution_id"] == "exec-5"
    pending_ids = [t["task_id"] for t in body["pending"]]
    assert pending_ids == [t2]


# ── 503：未装配 ──────────────────────────────────────────────────────────────


async def test_503_when_store_not_configured():
    app, _, _ = _make_app(with_store=False, with_resolver=False)
    async with await _client(app) as client:
        resp = await client.get("/api/human-tasks/task/any")
    assert resp.status_code == 503


async def test_503_when_resolver_not_configured():
    """store 在但 resolver 缺失 → approve 503（挂起/查询仍可用，只是审批面未装配）。"""
    app, _, _ = _make_app(with_store=True, with_resolver=False)
    async with await _client(app) as client:
        resp = await client.post("/api/human-tasks/any/approve", json={"comment": ""})
    assert resp.status_code == 503


# ── _suspend_status 映射（第二段接线的落点）─────────────────────────────────


def test_suspend_status_maps_human_to_waiting_human():
    assert _suspend_status("human") is ExecutionStatus.WAITING_HUMAN
    assert _suspend_status("HUMAN") is ExecutionStatus.WAITING_HUMAN  # 大小写不敏感


def test_suspend_status_maps_everything_else_to_waiting_external():
    assert _suspend_status("external") is ExecutionStatus.WAITING_EXTERNAL
    assert _suspend_status(None) is ExecutionStatus.WAITING_EXTERNAL
    assert _suspend_status("timer") is ExecutionStatus.WAITING_EXTERNAL
    assert _suspend_status("") is ExecutionStatus.WAITING_EXTERNAL


# ── 视图不回传内部全量 metadata ──────────────────────────────────────────────


async def test_view_does_not_leak_full_metadata():
    """_view 只暴露审批所需字段，不回传 metadata 全量（如内部 context/skill_name）。"""
    app, _, _ = _make_app()
    task_id = await _seed_human_task(app, "exec-6", waiting_status=False)

    async with await _client(app) as client:
        resp = await client.get(f"/api/human-tasks/task/{task_id}")

    view = resp.json()
    assert "metadata" not in view
    # context（含 contract_id）不进对外视图
    assert "contract_id" not in json.dumps(view, ensure_ascii=False)
    # 但 kind 恒为 HUMAN（store 层已保证），视图字段集合固定
    assert set(view) == {
        "task_id", "execution_id", "step_id", "state",
        "prompt", "options", "deadline", "submitted_by",
        "completion_receipt", "resume_payload",
    }
    # 冗余防御：确认这条任务确实是 HUMAN（而非误建 EXTERNAL）
    loaded = await app.state.human_task_store.get(task_id)
    assert loaded.kind is AwaitableKind.HUMAN
