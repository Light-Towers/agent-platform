"""V3-3 单测：durable execution status state machine + Awaitable Task。

验证：
- ExecutionStatus 状态机（合法/非法转换、terminal / awaiting 判定）；
- ExecutionStatusStore（InMemory）：状态转换校验 + generation fencing；
- AwaitableState 状态机（含 UNKNOWN → 确定态的恢复路径）；
- AwaitableTaskStore（InMemory）：save/load/list_by_execution/list_unresolved；
- AwaitableKind 四类（External / Human / Timer / Callback）；
- crash recovery 语义：UNKNOWN → query → COMPLETED。
"""

import pytest

from agent_runtime.awaitable_task import (
    AwaitableKind,
    AwaitableState,
    AwaitableTask,
    InMemoryAwaitableTaskStore,
    InvalidTaskTransition,
)
from agent_runtime.awaitable_task import (
    can_transition as can_task_transition,
)
from agent_runtime.execution_status import (
    ExecutionStatus,
    ExecutionStatusRecord,
    InMemoryExecutionStatusStore,
    InvalidStatusTransition,
    can_transition,
)

# ===== ExecutionStatus 状态机 =====

def test_status_terminal_and_awaiting():
    assert ExecutionStatus.SUCCEEDED.is_terminal
    assert ExecutionStatus.FAILED.is_terminal
    assert ExecutionStatus.CANCELLED.is_terminal
    assert not ExecutionStatus.RUNNING.is_terminal

    assert ExecutionStatus.WAITING_EXTERNAL.is_awaiting
    assert ExecutionStatus.WAITING_HUMAN.is_awaiting
    assert ExecutionStatus.PAUSED.is_awaiting
    assert not ExecutionStatus.RUNNING.is_awaiting


def test_status_transitions_legal():
    assert can_transition(ExecutionStatus.PENDING, ExecutionStatus.RUNNING)
    assert can_transition(ExecutionStatus.RUNNING, ExecutionStatus.WAITING_HUMAN)
    assert can_transition(ExecutionStatus.WAITING_HUMAN, ExecutionStatus.RUNNING)
    assert can_transition(ExecutionStatus.RUNNING, ExecutionStatus.CANCEL_REQUESTED)
    assert can_transition(ExecutionStatus.CANCEL_REQUESTED, ExecutionStatus.CANCELLED)
    assert can_transition(ExecutionStatus.RUNNING, ExecutionStatus.SUCCEEDED)


def test_status_transitions_illegal():
    assert not can_transition(ExecutionStatus.SUCCEEDED, ExecutionStatus.RUNNING)
    assert not can_transition(ExecutionStatus.CANCELLED, ExecutionStatus.RUNNING)
    assert not can_transition(ExecutionStatus.PENDING, ExecutionStatus.SUCCEEDED)
    assert not can_transition(ExecutionStatus.WAITING_HUMAN, ExecutionStatus.SUCCEEDED)


async def test_status_store_lifecycle():
    store = InMemoryExecutionStatusStore()
    assert await store.load("e1") is None

    await store.save(ExecutionStatusRecord("e1", ExecutionStatus.PENDING))
    await store.save(ExecutionStatusRecord("e1", ExecutionStatus.RUNNING))
    await store.save(ExecutionStatusRecord("e1", ExecutionStatus.WAITING_HUMAN))
    await store.save(ExecutionStatusRecord("e1", ExecutionStatus.RUNNING))
    await store.save(ExecutionStatusRecord("e1", ExecutionStatus.SUCCEEDED))

    rec = await store.load("e1")
    assert rec.status is ExecutionStatus.SUCCEEDED


async def test_status_store_rejects_illegal_transition():
    store = InMemoryExecutionStatusStore()
    await store.save(ExecutionStatusRecord("e1", ExecutionStatus.SUCCEEDED))
    with pytest.raises(InvalidStatusTransition):
        await store.save(ExecutionStatusRecord("e1", ExecutionStatus.RUNNING))


async def test_status_store_generation_fencing():
    """旧 generation 写状态被拒（V3-1 fencing 扩展到 status）。"""
    store = InMemoryExecutionStatusStore()
    await store.save(
        ExecutionStatusRecord("e1", ExecutionStatus.RUNNING, generation=2)
    )
    with pytest.raises(InvalidStatusTransition):
        await store.save(
            ExecutionStatusRecord("e1", ExecutionStatus.WAITING, generation=1)
        )


# ===== AwaitableState 状态机 =====

def test_task_state_terminal_and_resolution():
    assert AwaitableState.COMPLETED.is_terminal
    assert AwaitableState.FAILED.is_terminal
    assert not AwaitableState.RUNNING.is_terminal
    # 需查询外部系统确定实际状态
    assert AwaitableState.UNKNOWN.needs_resolution
    assert AwaitableState.SUBMITTED.needs_resolution
    assert AwaitableState.RUNNING.needs_resolution
    assert not AwaitableState.COMPLETED.needs_resolution


def test_task_state_transitions():
    assert can_task_transition(AwaitableState.PENDING, AwaitableState.SUBMITTED)
    assert can_task_transition(AwaitableState.SUBMITTED, AwaitableState.RUNNING)
    assert can_task_transition(AwaitableState.RUNNING, AwaitableState.COMPLETED)
    assert can_task_transition(AwaitableState.RUNNING, AwaitableState.TIMED_OUT)
    assert can_task_transition(AwaitableState.SUBMITTED, AwaitableState.UNKNOWN)
    # UNKNOWN 经 query 收敛
    assert can_task_transition(AwaitableState.UNKNOWN, AwaitableState.COMPLETED)
    assert can_task_transition(AwaitableState.UNKNOWN, AwaitableState.FAILED)
    # 终态不可再转换
    assert not can_task_transition(AwaitableState.COMPLETED, AwaitableState.RUNNING)
    assert not can_task_transition(AwaitableState.PENDING, AwaitableState.COMPLETED)


# ===== AwaitableTaskStore =====

async def test_awaitable_task_store_crud():
    store = InMemoryAwaitableTaskStore()
    task = AwaitableTask(
        execution_id="e1", step_id="n1", kind=AwaitableKind.EXTERNAL, provider="video-api"
    )
    await store.save(task)

    loaded = await store.load(task.task_id)
    assert loaded is not None
    assert loaded.state is AwaitableState.PENDING
    assert loaded.kind is AwaitableKind.EXTERNAL

    # 推进状态
    task.state = AwaitableState.SUBMITTED
    task.provider_task_id = "job-123"
    task.submission_receipt = {"accepted": True}
    task.submitted_at = 1000.0
    await store.save(task)

    loaded = await store.load(task.task_id)
    assert loaded.state is AwaitableState.SUBMITTED
    assert loaded.provider_task_id == "job-123"
    assert loaded.submission_receipt == {"accepted": True}


async def test_awaitable_task_store_rejects_illegal_transition():
    store = InMemoryAwaitableTaskStore()
    task = AwaitableTask(
        execution_id="e1", step_id="n1", kind=AwaitableKind.EXTERNAL, provider="api"
    )
    task.state = AwaitableState.COMPLETED
    await store.save(task)
    task.state = AwaitableState.RUNNING
    with pytest.raises(InvalidTaskTransition):
        await store.save(task)


async def test_awaitable_task_store_list_by_execution_and_unresolved():
    store = InMemoryAwaitableTaskStore()
    t1 = AwaitableTask(execution_id="e1", step_id="n1", kind=AwaitableKind.EXTERNAL, provider="api")
    t2 = AwaitableTask(execution_id="e1", step_id="n2", kind=AwaitableKind.HUMAN, provider="human")
    t3 = AwaitableTask(execution_id="e2", step_id="n1", kind=AwaitableKind.TIMER, provider="timer")
    await store.save(t1)
    await store.save(t2)
    await store.save(t3)

    e1_tasks = await store.list_by_execution("e1")
    assert len(e1_tasks) == 2
    assert {t.step_id for t in e1_tasks} == {"n1", "n2"}

    # 全部非终态 → unresolved 3 个
    assert len(await store.list_unresolved()) == 3

    # t1 收敛 → unresolved 2 个（走合法路径 PENDING → SUBMITTED → COMPLETED）
    t1.state = AwaitableState.SUBMITTED
    await store.save(t1)
    t1.state = AwaitableState.COMPLETED
    await store.save(t1)
    assert len(await store.list_unresolved()) == 2


async def test_all_awaitable_kinds():
    store = InMemoryAwaitableTaskStore()
    for kind in AwaitableKind:
        t = AwaitableTask(execution_id="e1", step_id=f"n_{kind.value}", kind=kind, provider=kind.value)
        await store.save(t)
    tasks = await store.list_by_execution("e1")
    assert {t.kind for t in tasks} == set(AwaitableKind)


async def test_crash_recovery_unknown_resolves_completed():
    """crash recovery 语义：SUBMITTED 后 crash → UNKNOWN → query → COMPLETED。"""
    store = InMemoryAwaitableTaskStore()
    task = AwaitableTask(
        execution_id="e1", step_id="n1", kind=AwaitableKind.EXTERNAL, provider="video-api"
    )
    task.state = AwaitableState.SUBMITTED
    task.provider_task_id = "job-9"
    await store.save(task)

    # 模拟 crash 后：状态不确定 → 标 UNKNOWN
    task.state = AwaitableState.UNKNOWN
    await store.save(task)

    # query 外部系统确认已成功 → COMPLETED + completion_receipt
    task.state = AwaitableState.COMPLETED
    task.completion_receipt = {"video_url": "s3://x"}
    task.completed_at = 2000.0
    await store.save(task)

    loaded = await store.load(task.task_id)
    assert loaded.state is AwaitableState.COMPLETED
    assert loaded.completion_receipt == {"video_url": "s3://x"}
    assert loaded.state.is_terminal