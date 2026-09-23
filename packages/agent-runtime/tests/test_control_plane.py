"""V3-5B 单测：Execution Control Plane。

验证：
- inspect：完整快照（status / queue_status / checkpoint / external_tasks）；
- pause / resume：RUNNING ↔ PAUSED；
- cancel：QUEUED 直接取消 / RUNNING → CANCEL_REQUESTED；
- retry：标记旧 FAILED + 重新入队；
- terminate：强制终止。
"""


from agent_runtime.control_plane import ControlPlane, ExecutionSnapshot
from agent_runtime.execution_scheduler import (
    ExecutionPriority,
    ExecutionRequest,
    ExecutionScheduler,
    InMemorySchedulerStore,
    QueueStatus,
    SchedulerConfig,
)
from agent_runtime.execution_status import (
    ExecutionStatus,
    ExecutionStatusRecord,
    InMemoryExecutionStatusStore,
)


def _req(execution_id: str = "e1", tenant_id: str = "t1") -> ExecutionRequest:
    return ExecutionRequest(
        execution_id=execution_id,
        tenant_id=tenant_id,
        session_id="s1",
        user_id="u1",
        priority=ExecutionPriority.NORMAL,
    )


async def test_inspect_queued():
    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store)
    await scheduler.submit(_req("e1"))

    cp = ControlPlane(scheduler)
    snap = await cp.inspect("e1")
    assert snap is not None
    assert snap.execution_id == "e1"
    assert snap.queue_status is QueueStatus.QUEUED
    assert snap.tenant_id == "t1"


async def test_inspect_with_status_store():
    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store)
    status_store = InMemoryExecutionStatusStore()
    await scheduler.submit(_req("e1"))
    await status_store.save(ExecutionStatusRecord("e1", ExecutionStatus.RUNNING, generation=1))

    cp = ControlPlane(scheduler, status_store=status_store)
    snap = await cp.inspect("e1")
    assert snap.status is ExecutionStatus.RUNNING
    assert snap.generation == 1


async def test_inspect_nonexistent():
    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store)
    cp = ControlPlane(scheduler)
    assert await cp.inspect("nonexistent") is None


async def test_pause_and_resume():
    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store)
    status_store = InMemoryExecutionStatusStore()
    await scheduler.submit(_req("e1"))
    await status_store.save(ExecutionStatusRecord("e1", ExecutionStatus.RUNNING, generation=1))

    cp = ControlPlane(scheduler, status_store=status_store)
    assert await cp.pause("e1") is True

    rec = await status_store.load("e1")
    assert rec.status is ExecutionStatus.PAUSED

    assert await cp.resume("e1") is True
    rec = await status_store.load("e1")
    assert rec.status is ExecutionStatus.RUNNING


async def test_pause_non_running_fails():
    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store)
    status_store = InMemoryExecutionStatusStore()
    await scheduler.submit(_req("e1"))
    await status_store.save(ExecutionStatusRecord("e1", ExecutionStatus.PENDING))

    cp = ControlPlane(scheduler, status_store=status_store)
    assert await cp.pause("e1") is False


async def test_cancel_queued():
    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store)
    await scheduler.submit(_req("e1"))

    cp = ControlPlane(scheduler)
    assert await cp.cancel("e1") is True
    assert await scheduler.queue_depth() == 0


async def test_cancel_running_with_status():
    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store)
    status_store = InMemoryExecutionStatusStore()
    await scheduler.submit(_req("e1"))
    await scheduler.dispatch_next()
    await status_store.save(ExecutionStatusRecord("e1", ExecutionStatus.RUNNING, generation=1))

    cp = ControlPlane(scheduler, status_store=status_store)
    assert await cp.cancel("e1") is True

    rec = await status_store.load("e1")
    assert rec.status is ExecutionStatus.CANCEL_REQUESTED


async def test_retry():
    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store, SchedulerConfig(max_concurrent=10))
    await scheduler.submit(_req("e1"))

    cp = ControlPlane(scheduler)
    new_id = await cp.retry("e1")
    assert new_id is not None
    assert "retry" in new_id

    old = await scheduler.get("e1")
    assert old.status is QueueStatus.FAILED

    new = await scheduler.get(new_id)
    assert new.status is QueueStatus.QUEUED
    assert new.metadata["recovery_attempts"] == 1


async def test_terminate():
    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store)
    status_store = InMemoryExecutionStatusStore()
    await scheduler.submit(_req("e1"))
    await scheduler.dispatch_next()
    await status_store.save(ExecutionStatusRecord("e1", ExecutionStatus.RUNNING, generation=1))

    cp = ControlPlane(scheduler, status_store=status_store)
    assert await cp.terminate("e1") is True

    req = await scheduler.get("e1")
    assert req.status is QueueStatus.FAILED

    rec = await status_store.load("e1")
    assert rec.status is ExecutionStatus.FAILED


async def test_terminate_already_terminal():
    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store)
    await scheduler.submit(_req("e1"))
    await scheduler.complete("e1", QueueStatus.COMPLETED)

    cp = ControlPlane(scheduler)
    assert await cp.terminate("e1") is True


async def test_snapshot_to_dict():
    snap = ExecutionSnapshot(
        execution_id="e1",
        tenant_id="t1",
        status=ExecutionStatus.RUNNING,
        queue_status=QueueStatus.RUNNING,
    )
    d = snap.to_dict()
    assert d["execution_id"] == "e1"
    assert d["status"] == "running"
    assert d["queue_status"] == "running"
