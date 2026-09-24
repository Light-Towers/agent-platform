"""V3 补-1 单测：Human Task / Approval。

验证：
- HumanTaskStore：create / submit / resolve / reject / list_pending；
- HumanTaskResolver：resolve_and_resume / reject_and_fail；
- 状态流转：PENDING → SUBMITTED → COMPLETED/FAILED；
- ExecutionStatus 联动：WAITING_HUMAN → RUNNING / FAILED。
"""


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
    HumanTaskDecision,
    HumanTaskResolver,
    HumanTaskStore,
)

# ===== HumanTaskStore =====

async def test_create_human_task():
    awaitable_store = InMemoryAwaitableTaskStore()
    human_store = HumanTaskStore(awaitable_store)

    task = HumanTask(
        execution_id="e1",
        step_id="approval",
        prompt="请审批此合同变更",
        options=["approve", "reject", "defer"],
        approver="manager_a",
        context={"contract_id": "C001", "amount": 50000},
    )
    awaitable = await human_store.create(task)
    assert awaitable.kind is AwaitableKind.HUMAN
    assert awaitable.state is AwaitableState.PENDING
    assert task.task_id is not None
    assert task.state is AwaitableState.PENDING


async def test_submit_human_task():
    awaitable_store = InMemoryAwaitableTaskStore()
    human_store = HumanTaskStore(awaitable_store)

    task = HumanTask(execution_id="e1", step_id="approval", prompt="审批")
    await human_store.create(task)
    await human_store.submit(task.task_id, "manager_a")

    loaded = await human_store.get(task.task_id)
    assert loaded.state is AwaitableState.SUBMITTED
    assert loaded.provider_task_id == "manager_a"


async def test_resolve_human_task():
    awaitable_store = InMemoryAwaitableTaskStore()
    human_store = HumanTaskStore(awaitable_store)

    task = HumanTask(execution_id="e1", step_id="approval", prompt="审批")
    await human_store.create(task)

    resolved = await human_store.resolve(
        task.task_id, HumanTaskDecision.APPROVED, "manager_a", "同意"
    )
    assert resolved.state is AwaitableState.COMPLETED
    assert resolved.completion_receipt["decision"] == "approved"
    assert resolved.completion_receipt["approver"] == "manager_a"
    assert resolved.resume_payload["decision"] == "approved"


async def test_resolve_from_pending_skips_submit():
    """resolve 直接从 PENDING 调用，自动补 SUBMITTED。"""
    awaitable_store = InMemoryAwaitableTaskStore()
    human_store = HumanTaskStore(awaitable_store)

    task = HumanTask(execution_id="e1", step_id="approval", prompt="审批")
    await human_store.create(task)

    resolved = await human_store.resolve(task.task_id, HumanTaskDecision.APPROVED, "mgr")
    assert resolved.state is AwaitableState.COMPLETED


async def test_reject_human_task():
    awaitable_store = InMemoryAwaitableTaskStore()
    human_store = HumanTaskStore(awaitable_store)

    task = HumanTask(execution_id="e1", step_id="approval", prompt="审批")
    await human_store.create(task)

    rejected = await human_store.reject(task.task_id, "manager_b", "金额超限")
    assert rejected.state is AwaitableState.FAILED
    assert rejected.completion_receipt["decision"] == "rejected"


async def test_list_pending():
    awaitable_store = InMemoryAwaitableTaskStore()
    human_store = HumanTaskStore(awaitable_store)

    t1 = HumanTask(execution_id="e1", step_id="a1", prompt="审批1")
    t2 = HumanTask(execution_id="e1", step_id="a2", prompt="审批2")
    await human_store.create(t1)
    await human_store.create(t2)
    await human_store.resolve(t1.task_id, HumanTaskDecision.APPROVED, "mgr")

    pending = await human_store.list_pending("e1")
    assert len(pending) == 1
    assert pending[0].step_id == "a2"


async def test_get_nonexistent():
    awaitable_store = InMemoryAwaitableTaskStore()
    human_store = HumanTaskStore(awaitable_store)
    assert await human_store.get("nonexistent") is None


# ===== HumanTaskResolver =====

async def test_resolve_and_resume():
    awaitable_store = InMemoryAwaitableTaskStore()
    status_store = InMemoryExecutionStatusStore()
    human_store = HumanTaskStore(awaitable_store)

    await status_store.save(ExecutionStatusRecord("e1", ExecutionStatus.WAITING_HUMAN, generation=1))

    task = HumanTask(execution_id="e1", step_id="approval", prompt="审批")
    await human_store.create(task)

    resolver = HumanTaskResolver(human_store, status_store)
    await resolver.resolve_and_resume(task.task_id, HumanTaskDecision.APPROVED, "mgr", "同意")

    rec = await status_store.load("e1")
    assert rec.status is ExecutionStatus.RUNNING

    loaded = await human_store.get(task.task_id)
    assert loaded.state is AwaitableState.COMPLETED


async def test_reject_and_fail():
    awaitable_store = InMemoryAwaitableTaskStore()
    status_store = InMemoryExecutionStatusStore()
    human_store = HumanTaskStore(awaitable_store)

    await status_store.save(ExecutionStatusRecord("e1", ExecutionStatus.WAITING_HUMAN, generation=1))

    task = HumanTask(execution_id="e1", step_id="approval", prompt="审批")
    await human_store.create(task)

    resolver = HumanTaskResolver(human_store, status_store)
    await resolver.reject_and_fail(task.task_id, "mgr", "不合规")

    rec = await status_store.load("e1")
    assert rec.status is ExecutionStatus.FAILED

    loaded = await human_store.get(task.task_id)
    assert loaded.state is AwaitableState.FAILED


async def test_resolve_without_status_store():
    """无 status_store 时只更新 task，不联动 ExecutionStatus。"""
    awaitable_store = InMemoryAwaitableTaskStore()
    human_store = HumanTaskStore(awaitable_store)

    task = HumanTask(execution_id="e1", step_id="approval", prompt="审批")
    await human_store.create(task)

    resolver = HumanTaskResolver(human_store)
    resolved = await resolver.resolve_and_resume(task.task_id, HumanTaskDecision.APPROVED, "mgr")
    assert resolved.state is AwaitableState.COMPLETED


# ===== HumanTask 属性 =====

def test_human_task_properties():
    task = HumanTask(
        execution_id="e1",
        step_id="approval",
        prompt="审批",
        options=["yes", "no"],
        approver="mgr",
    )
    assert task.task_id is None  # 尚未 create
    assert task.state is None
    assert task.options == ["yes", "no"]


def test_human_task_decision_values():
    assert HumanTaskDecision.APPROVED.value == "approved"
    assert HumanTaskDecision.REJECTED.value == "rejected"
    assert HumanTaskDecision.DEFERRED.value == "deferred"
