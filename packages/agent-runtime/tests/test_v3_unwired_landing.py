"""V3「未接线半成品转正」批的新增行为断言。

对应方案 `docs/plans/plan-v3-unwired-landing-2026-10-15.md` §4 验收 4 的项 2 / 项 3：
- ``SchedulerStore.requeue``（InMemory 白名单 + 后端不支持时收窄为 False）；
- ``SchedulerReaper`` 注入 recovery 后按契约决策，且**不绕过 lease 安全门**；
- ``ControlPlane.requeue`` / ``ControlPlane.recover``。

这些用例的判据是「装配与决策真发生了」，不是「没抛异常」。
"""

from agent_runtime.control_plane import ControlPlane
from agent_runtime.execution_recovery import ReaperConfig, RecoveryOrchestrator
from agent_runtime.execution_scheduler import (
    ExecutionPriority,
    ExecutionRequest,
    ExecutionScheduler,
    InMemorySchedulerStore,
    QueueStatus,
    SchedulerConfig,
    SchedulerReaper,
    SchedulerStore,
)


def _req(execution_id: str = "e1", tenant_id: str = "t1", **kwargs) -> ExecutionRequest:
    return ExecutionRequest(
        execution_id=execution_id,
        tenant_id=tenant_id,
        session_id="s1",
        user_id="u1",
        priority=ExecutionPriority.NORMAL,
        **kwargs,
    )


async def _done():
    return None


async def _park_running(scheduler, store, execution_id: str = "e1") -> None:
    """把执行推进到 RUNNING 且 dispatched_at=0.0（即已超时，供 Reaper 扫到）。"""
    await scheduler.submit(_req(execution_id))
    assert await scheduler.try_start(execution_id) is not None
    current = await store.get(execution_id)
    assert current is not None
    current.dispatched_at = 0.0
    store._store[execution_id] = current


# ===== requeue：store 白名单 =====


async def test_requeue_from_failed_cancelled_dispatched():
    for setup_status in (QueueStatus.FAILED, QueueStatus.CANCELLED, QueueStatus.DISPATCHED):
        store = InMemorySchedulerStore()
        await store.enqueue(_req("e1"))
        row = await store.get("e1")
        row.status = setup_status
        row.worker_id = "worker-x"
        row.dispatched_at = 123.0
        store._store["e1"] = row

        assert await store.requeue("e1") is True, setup_status
        after = await store.get("e1")
        assert after.status is QueueStatus.QUEUED
        # 派发痕迹必须清干净，否则 dequeue/try_start 的超时判定会立刻把它当 stuck
        assert after.worker_id is None
        assert after.dispatched_at is None


async def test_requeue_rejected_from_completed_queued_running():
    for setup_status in (QueueStatus.COMPLETED, QueueStatus.QUEUED, QueueStatus.RUNNING):
        store = InMemorySchedulerStore()
        await store.enqueue(_req("e1"))
        row = await store.get("e1")
        row.status = setup_status
        store._store["e1"] = row

        assert await store.requeue("e1") is False, setup_status
        after = await store.get("e1")
        assert after.status is setup_status


async def test_requeue_missing_execution_returns_false():
    store = InMemorySchedulerStore()
    assert await store.requeue("nope") is False


async def test_scheduler_requeue_narrows_unsupported_backend_to_false():
    """后端不支持 requeue 时不得冒 NotImplementedError（HTTP 层会变成 500）。

    替身镜像真实契约：``SchedulerStore.requeue`` 的基类默认实现就是抛
    ``NotImplementedError``（见 execution_scheduler.py 的 docstring）。
    """

    class _NoRequeueStore(InMemorySchedulerStore):
        async def requeue(self, execution_id: str) -> bool:
            raise NotImplementedError(f"{type(self).__name__} 不支持 requeue")

    store = _NoRequeueStore()
    scheduler = ExecutionScheduler(store)
    await scheduler.submit(_req("e1"))
    await scheduler.complete("e1", QueueStatus.FAILED)

    assert await scheduler.requeue("e1") is False


async def test_base_store_requeue_is_not_abstract():
    """基类 requeue 必须是**具体**方法：新增抽象方法会让既有替身无法实例化。"""
    assert "requeue" not in SchedulerStore.__abstractmethods__


# ===== SchedulerReaper × recovery =====


class _ExpiredOwnership:
    """lease 已失效（get_owner 恒 None），并在首次调用时停掉 Reaper 循环。"""

    def __init__(self):
        self.reaper = None
        self.calls = 0

    async def get_owner(self, execution_id):
        self.calls += 1
        self.reaper._stopped = True
        return None


class _LiveOwnership:
    """lease 仍有效（Worker 还在跑）。"""

    def __init__(self):
        self.reaper = None
        self.calls = 0

    async def get_owner(self, execution_id):
        self.calls += 1
        self.reaper._stopped = True
        return "worker-1"


async def test_reaper_with_recovery_requeues_instead_of_plain_fail(monkeypatch):
    """缺口 4 的 reschedule：lease 失效 ⇒ 旧执行 FAILED + 新 `:retry:1` 入队。"""
    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store, SchedulerConfig(max_concurrent=1))
    await _park_running(scheduler, store)

    ownership = _ExpiredOwnership()
    orch = RecoveryOrchestrator(scheduler, ReaperConfig(max_retries=3))
    reaper = SchedulerReaper(
        scheduler, ownership, interval_s=0, dispatch_timeout=1, running_timeout=1,
        recovery=orch,
    )
    ownership.reaper = reaper
    monkeypatch.setattr("agent_runtime.execution_scheduler.asyncio.sleep", lambda _: _done())
    await reaper.run()

    assert ownership.calls == 1  # 决策前确实过了 lease 门
    old = await store.get("e1")
    assert old.status is QueueStatus.FAILED
    retried = await store.get("e1:retry:1")
    assert retried is not None
    assert retried.status is QueueStatus.QUEUED
    assert retried.metadata["recovery_attempts"] == 1
    assert retried.metadata["recovered_from"] == "e1"
    assert retried.metadata["recovery_reason"] == "running_timeout"


async def test_reaper_recovery_does_not_bypass_lease_gate(monkeypatch):
    """剥掉 lease 门这条用例必红：owner 非 None 时既不 FAILED 也不重新入队。"""
    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store, SchedulerConfig(max_concurrent=1))
    await _park_running(scheduler, store)

    ownership = _LiveOwnership()
    orch = RecoveryOrchestrator(scheduler, ReaperConfig(max_retries=3))
    reaper = SchedulerReaper(
        scheduler, ownership, interval_s=0, dispatch_timeout=1, running_timeout=1,
        recovery=orch,
    )
    ownership.reaper = reaper
    monkeypatch.setattr("agent_runtime.execution_scheduler.asyncio.sleep", lambda _: _done())
    await reaper.run()

    current = await store.get("e1")
    assert current.status is QueueStatus.RUNNING
    assert await store.get("e1:retry:1") is None
    assert await scheduler.running_count() == 1


async def test_reaper_recovery_marks_failed_after_max_retries(monkeypatch):
    """重试次数超限 ⇒ 强制 MARK_FAILED，不再入队（无无限重试）。"""
    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store, SchedulerConfig(max_concurrent=1))
    await scheduler.submit(_req("e1", metadata={"recovery_attempts": 3}))
    assert await scheduler.try_start("e1") is not None
    current = await store.get("e1")
    current.dispatched_at = 0.0
    store._store["e1"] = current

    ownership = _ExpiredOwnership()
    orch = RecoveryOrchestrator(scheduler, ReaperConfig(max_retries=3))
    reaper = SchedulerReaper(
        scheduler, ownership, interval_s=0, dispatch_timeout=1, running_timeout=1,
        recovery=orch,
    )
    ownership.reaper = reaper
    monkeypatch.setattr("agent_runtime.execution_scheduler.asyncio.sleep", lambda _: _done())
    await reaper.run()

    old = await store.get("e1")
    assert old.status is QueueStatus.FAILED
    assert await store.get("e1:retry:4") is None
    assert await scheduler.queue_depth() == 0


async def test_reaper_without_recovery_keeps_legacy_behaviour(monkeypatch):
    """默认（未注入 recovery）逐字保持旧行为：只标 FAILED，不新建重试。"""
    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store, SchedulerConfig(max_concurrent=1))
    await _park_running(scheduler, store)

    ownership = _ExpiredOwnership()
    reaper = SchedulerReaper(
        scheduler, ownership, interval_s=0, dispatch_timeout=1, running_timeout=1
    )
    ownership.reaper = reaper
    monkeypatch.setattr("agent_runtime.execution_scheduler.asyncio.sleep", lambda _: _done())
    await reaper.run()

    old = await store.get("e1")
    assert old.status is QueueStatus.FAILED
    assert await store.get("e1:retry:1") is None


# ===== ControlPlane.requeue / recover =====


async def test_control_plane_requeue_from_failed():
    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store)
    await scheduler.submit(_req("e1"))
    await scheduler.complete("e1", QueueStatus.FAILED)

    cp = ControlPlane(scheduler)
    assert await cp.requeue("e1") is True
    after = await scheduler.get("e1")
    assert after.status is QueueStatus.QUEUED


async def test_control_plane_requeue_rejects_completed_and_missing():
    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store)
    await scheduler.submit(_req("e1"))
    await scheduler.complete("e1", QueueStatus.COMPLETED)

    cp = ControlPlane(scheduler)
    assert await cp.requeue("e1") is False
    assert await cp.requeue("nope") is False


async def test_control_plane_recover_returns_action_and_requeues():
    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store)
    await scheduler.submit(_req("e1"))
    await scheduler.complete("e1", QueueStatus.FAILED)

    orch = RecoveryOrchestrator(scheduler, ReaperConfig(max_retries=3))
    cp = ControlPlane(scheduler, recovery=orch)

    assert await cp.recover("e1") == "retry"
    assert await store.get("e1:retry:1") is not None


async def test_control_plane_recover_without_recovery_returns_none():
    """未开恢复开关时返回 None（API 层转 409），不假装恢复成功。"""
    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store)
    await scheduler.submit(_req("e1"))

    cp = ControlPlane(scheduler)
    assert await cp.recover("e1") is None
    assert await cp.recover("nope") is None


async def test_control_plane_recover_respects_contract_no_retry():
    """接上 contract_resolver 后，NO_RETRY 契约必须落成 mark_failed 而不是 retry。"""
    from agent_runtime.effect_contract import (
        EffectContract,
        FailureRecovery,
    )

    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store)
    await scheduler.submit(_req("e1"))
    await scheduler.complete("e1", QueueStatus.FAILED)

    contract = EffectContract(effect_key="k1", failure_recovery=FailureRecovery.NO_RETRY)
    orch = RecoveryOrchestrator(
        scheduler, ReaperConfig(max_retries=3), contract_resolver=lambda _eid: contract
    )
    cp = ControlPlane(scheduler, recovery=orch)

    assert await cp.recover("e1") == "mark_failed"
    assert await store.get("e1:retry:1") is None
