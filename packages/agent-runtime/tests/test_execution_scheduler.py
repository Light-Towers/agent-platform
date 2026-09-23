"""V3-4A 单测：Execution Scheduler（队列 + 优先级 + 公平性 + 槽位管理）。

验证：
- ExecutionPriority 权重排序；
- QueueStatus 状态机（terminal / occupies_slot）；
- InMemorySchedulerStore：enqueue / dequeue / mark_running / mark_completed / cancel；
- 优先级调度：high 优先于 normal 优先于 low；
- 公平性：per-tenant 已运行数少者优先；
- 槽位约束：全局 max_concurrent + per-tenant max_concurrent_per_tenant；
- Backpressure：队列满时 submit 抛 QueueFull；
- ExecutionScheduler 门面：submit / dispatch_next / complete / queue_depth。
"""

import pytest

from agent_runtime.execution_scheduler import (
    ExecutionPriority,
    ExecutionRequest,
    ExecutionScheduler,
    InMemorySchedulerStore,
    QueueFull,
    QueueStatus,
    SchedulerConfig,
)


def _req(
    execution_id: str = "e1",
    tenant_id: str = "t1",
    priority: ExecutionPriority = ExecutionPriority.NORMAL,
    created_at: float = 0.0,
) -> ExecutionRequest:
    return ExecutionRequest(
        execution_id=execution_id,
        tenant_id=tenant_id,
        session_id="s1",
        user_id="u1",
        priority=priority,
        created_at=created_at,
    )


# ===== 枚举 =====

def test_priority_weight():
    assert ExecutionPriority.HIGH.weight > ExecutionPriority.NORMAL.weight
    assert ExecutionPriority.NORMAL.weight > ExecutionPriority.LOW.weight


def test_queue_status_terminal_and_slot():
    assert QueueStatus.COMPLETED.is_terminal
    assert QueueStatus.FAILED.is_terminal
    assert QueueStatus.CANCELLED.is_terminal
    assert not QueueStatus.QUEUED.is_terminal
    assert not QueueStatus.DISPATCHED.is_terminal

    assert QueueStatus.DISPATCHED.occupies_slot
    assert QueueStatus.RUNNING.occupies_slot
    assert not QueueStatus.QUEUED.occupies_slot
    assert not QueueStatus.COMPLETED.occupies_slot


# ===== InMemorySchedulerStore 基础 CRUD =====

async def test_enqueue_and_get():
    store = InMemorySchedulerStore()
    req = _req("e1")
    await store.enqueue(req)
    loaded = await store.get("e1")
    assert loaded is not None
    assert loaded.execution_id == "e1"
    assert loaded.status is QueueStatus.QUEUED


async def test_dequeue_basic():
    store = InMemorySchedulerStore()
    await store.enqueue(_req("e1", created_at=1.0))
    got = await store.dequeue(SchedulerConfig())
    assert got is not None
    assert got.execution_id == "e1"
    assert got.status is QueueStatus.DISPATCHED
    assert got.worker_id is not None
    assert got.dispatched_at is not None


async def test_dequeue_empty_returns_none():
    store = InMemorySchedulerStore()
    assert await store.dequeue(SchedulerConfig()) is None


async def test_mark_running_and_completed():
    store = InMemorySchedulerStore()
    await store.enqueue(_req("e1"))
    got = await store.dequeue(SchedulerConfig())
    assert got is not None

    worker = got.worker_id or "w1"
    await store.mark_running("e1", worker)
    loaded = await store.get("e1")
    assert loaded.status is QueueStatus.RUNNING
    assert loaded.worker_id == worker

    await store.mark_completed("e1", QueueStatus.COMPLETED)
    loaded = await store.get("e1")
    assert loaded.status is QueueStatus.COMPLETED
    assert loaded.status.is_terminal


async def test_cancel_queued():
    store = InMemorySchedulerStore()
    await store.enqueue(_req("e1"))
    assert await store.cancel("e1") is True
    loaded = await store.get("e1")
    assert loaded.status is QueueStatus.CANCELLED


async def test_cancel_running_fails():
    store = InMemorySchedulerStore()
    await store.enqueue(_req("e1"))
    await store.dequeue(SchedulerConfig())
    assert await store.cancel("e1") is False


# ===== 优先级调度 =====

async def test_priority_high_before_normal():
    store = InMemorySchedulerStore()
    await store.enqueue(_req("e_low", priority=ExecutionPriority.LOW, created_at=0.0))
    await store.enqueue(_req("e_high", priority=ExecutionPriority.HIGH, created_at=2.0))
    await store.enqueue(_req("e_norm", priority=ExecutionPriority.NORMAL, created_at=1.0))

    order = []
    for _ in range(3):
        got = await store.dequeue(SchedulerConfig(max_concurrent=10))
        assert got is not None
        order.append(got.execution_id)
    assert order == ["e_high", "e_norm", "e_low"]


async def test_same_priority_fifo():
    store = InMemorySchedulerStore()
    await store.enqueue(_req("e3", created_at=3.0))
    await store.enqueue(_req("e1", created_at=1.0))
    await store.enqueue(_req("e2", created_at=2.0))

    order = []
    for _ in range(3):
        got = await store.dequeue(SchedulerConfig(max_concurrent=10))
        assert got is not None
        order.append(got.execution_id)
    assert order == ["e1", "e2", "e3"]


# ===== 公平性 =====

async def test_fairness_tenant_round_robin():
    """同 priority 下，已运行少的 tenant 优先。"""
    store = InMemorySchedulerStore()
    config = SchedulerConfig(max_concurrent=10, max_concurrent_per_tenant=5)

    await store.enqueue(_req("a1", tenant_id="ta", created_at=1.0))
    await store.enqueue(_req("a2", tenant_id="ta", created_at=2.0))
    await store.enqueue(_req("b1", tenant_id="tb", created_at=3.0))

    got1 = await store.dequeue(config)
    assert got1 is not None
    assert got1.tenant_id == "ta"

    got2 = await store.dequeue(config)
    assert got2 is not None
    assert got2.tenant_id == "tb"

    got3 = await store.dequeue(config)
    assert got3 is not None
    assert got3.tenant_id == "ta"


# ===== 槽位约束 =====

async def test_global_concurrency_limit():
    store = InMemorySchedulerStore()
    config = SchedulerConfig(max_concurrent=2)

    await store.enqueue(_req("e1", created_at=1.0))
    await store.enqueue(_req("e2", created_at=2.0))
    await store.enqueue(_req("e3", created_at=3.0))

    assert await store.dequeue(config) is not None
    assert await store.dequeue(config) is not None
    assert await store.dequeue(config) is None

    await store.mark_completed("e1", QueueStatus.COMPLETED)
    got = await store.dequeue(config)
    assert got is not None
    assert got.execution_id == "e3"


async def test_per_tenant_concurrency_limit():
    """per-tenant 槽位约束：ta 已占 2 槽时，a3 被挡住，只有 tb 可选。"""
    store = InMemorySchedulerStore()
    config = SchedulerConfig(max_concurrent=10, max_concurrent_per_tenant=2)

    await store.enqueue(_req("a1", tenant_id="ta", created_at=1.0))
    await store.enqueue(_req("a2", tenant_id="ta", created_at=2.0))
    await store.enqueue(_req("a3", tenant_id="ta", created_at=3.0))
    await store.enqueue(_req("b1", tenant_id="tb", created_at=4.0))

    # dequeue 1: a1（ta, tenant_running=0，created_at 最早）
    got1 = await store.dequeue(config)
    assert got1 is not None and got1.execution_id == "a1"
    # dequeue 2: b1（tb, tenant_running=0，fairness 优先于 ta 的 1）
    got2 = await store.dequeue(config)
    assert got2 is not None and got2.execution_id == "b1"
    # dequeue 3: a2（ta, tenant_running=1 < 2）
    got3 = await store.dequeue(config)
    assert got3 is not None and got3.execution_id == "a2"
    # dequeue 4: None — a3 的 tenant_running=2 >= 2，b1 已占槽
    assert await store.dequeue(config) is None

    # 释放 a1 → a3 可入
    await store.mark_completed("a1", QueueStatus.COMPLETED)
    got = await store.dequeue(config)
    assert got is not None and got.execution_id == "a3"


# ===== Backpressure =====

async def test_backpressure_queue_full():
    store = InMemorySchedulerStore()
    config = SchedulerConfig(queue_capacity=2)
    scheduler = ExecutionScheduler(store, config)

    await scheduler.submit(_req("e1"))
    await scheduler.submit(_req("e2"))
    with pytest.raises(QueueFull):
        await scheduler.submit(_req("e3"))


# ===== ExecutionScheduler 门面 =====

async def test_scheduler_facade():
    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store, SchedulerConfig(max_concurrent=2))

    await scheduler.submit(_req("e1", priority=ExecutionPriority.HIGH))
    await scheduler.submit(_req("e2", priority=ExecutionPriority.LOW))

    assert await scheduler.queue_depth() == 2
    assert await scheduler.running_count() == 0

    got = await scheduler.dispatch_next()
    assert got is not None
    assert got.execution_id == "e1"
    assert await scheduler.queue_depth() == 1
    assert await scheduler.running_count() == 1

    await scheduler.mark_running("e1", "worker-1")
    got2 = await scheduler.dispatch_next()
    assert got2 is not None
    assert got2.execution_id == "e2"

    assert await scheduler.dispatch_next() is None

    await scheduler.complete("e1", QueueStatus.COMPLETED)
    assert await scheduler.running_count() == 1

    await scheduler.complete("e2", QueueStatus.FAILED)
    assert await scheduler.running_count() == 0


async def test_scheduler_cancel():
    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store)

    await scheduler.submit(_req("e1"))
    assert await scheduler.cancel("e1") is True
    assert await scheduler.queue_depth() == 0
