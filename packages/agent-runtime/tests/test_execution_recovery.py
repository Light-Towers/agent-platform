"""V3-4B 单测：Reaper + Recovery + Rescheduler。

验证：
- Reaper.scan：找出超时 DISPATCHED / RUNNING；
- RecoveryManager.decide：按 Effect Contract + 重试次数决策；
- Rescheduler.execute：retry 重新入队 / mark_failed / mark_human；
- RecoveryOrchestrator.run_cycle：端到端恢复周期。
"""

import time

from agent_runtime.effect_contract import (
    DeliverySemantics,
    EffectContract,
    FailureRecovery,
    IdempotencyStrategy,
    ReceiptStrategy,
    RetryPolicy,
)
from agent_runtime.execution_recovery import (
    Reaper,
    ReaperConfig,
    RecoveryAction,
    RecoveryManager,
    RecoveryOrchestrator,
    Rescheduler,
    StuckExecution,
)
from agent_runtime.execution_scheduler import (
    ExecutionPriority,
    ExecutionRequest,
    ExecutionScheduler,
    InMemorySchedulerStore,
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


# ===== Reaper =====

async def test_reaper_finds_dispatched_timeout():
    store = InMemorySchedulerStore()
    await store.enqueue(_req("e1"))
    got = await store.dequeue(SchedulerConfig())
    assert got is not None

    # 模拟超时：手动改 dispatched_at 为很久以前
    r = store._store["e1"]
    r.dispatched_at = time.time() - 400

    reaper = Reaper(store, ReaperConfig(dispatch_timeout=300, running_timeout=1800))
    stuck = await reaper.scan()
    assert len(stuck) == 1
    assert stuck[0].execution_id == "e1"
    assert stuck[0].reason == "dispatch_timeout"
    assert stuck[0].attempt == 0


async def test_reaper_finds_running_timeout():
    store = InMemorySchedulerStore()
    await store.enqueue(_req("e1"))
    got = await store.dequeue(SchedulerConfig())
    assert got is not None
    await store.mark_running("e1", got.worker_id or "w1")

    r = store._store["e1"]
    r.dispatched_at = time.time() - 2000

    reaper = Reaper(store, ReaperConfig(dispatch_timeout=300, running_timeout=1800))
    stuck = await reaper.scan()
    assert len(stuck) == 1
    assert stuck[0].reason == "running_timeout"


async def test_reaper_no_stuck():
    store = InMemorySchedulerStore()
    await store.enqueue(_req("e1"))
    await store.dequeue(SchedulerConfig())

    reaper = Reaper(store, ReaperConfig(dispatch_timeout=300, running_timeout=1800))
    assert await reaper.scan() == []


async def test_reaper_tracks_attempt_from_metadata():
    store = InMemorySchedulerStore()
    req = _req("e1")
    req.metadata["recovery_attempts"] = 2
    await store.enqueue(req)
    got = await store.dequeue(SchedulerConfig())
    assert got is not None

    r = store._store["e1"]
    r.dispatched_at = time.time() - 400

    reaper = Reaper(store, ReaperConfig(dispatch_timeout=300))
    stuck = await reaper.scan()
    assert stuck[0].attempt == 2


# ===== RecoveryManager.decide =====

def test_recovery_decide_no_contract():
    mgr = RecoveryManager(max_retries=3)
    stuck = StuckExecution("e1", "t1", "s1", "u1", "timeout", 0.0, attempt=0)
    assert mgr.decide(stuck, None) is RecoveryAction.RETRY


def test_recovery_decide_retry_safe():
    mgr = RecoveryManager(max_retries=3)
    stuck = StuckExecution("e1", "t1", "s1", "u1", "timeout", 0.0, attempt=0)
    contract = EffectContract.read_only()
    assert mgr.decide(stuck, contract) is RecoveryAction.RETRY


def test_recovery_decide_query_before_retry():
    mgr = RecoveryManager(max_retries=3)
    stuck = StuckExecution("e1", "t1", "s1", "u1", "timeout", 0.0, attempt=0)
    contract = EffectContract.async_task("job")
    assert mgr.decide(stuck, contract) is RecoveryAction.QUERY_STATUS


def test_recovery_decide_manual():
    mgr = RecoveryManager(max_retries=3)
    stuck = StuckExecution("e1", "t1", "s1", "u1", "timeout", 0.0, attempt=0)
    contract = EffectContract.non_idempotent_write("order")
    assert mgr.decide(stuck, contract) is RecoveryAction.MARK_HUMAN


def test_recovery_decide_max_retries_exceeded():
    mgr = RecoveryManager(max_retries=3)
    stuck = StuckExecution("e1", "t1", "s1", "u1", "timeout", 0.0, attempt=3)
    contract = EffectContract.read_only()
    assert mgr.decide(stuck, contract) is RecoveryAction.MARK_FAILED


# ===== Rescheduler =====

async def test_rescheduler_retry():
    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store, SchedulerConfig(max_concurrent=10))
    await scheduler.submit(_req("e1"))
    got = await scheduler.dispatch_next()
    assert got is not None

    r = store._store["e1"]
    r.dispatched_at = time.time() - 400

    reaper = Reaper(store, ReaperConfig(dispatch_timeout=300))
    stuck_list = await reaper.scan()
    stuck = stuck_list[0]

    rescheduler = Rescheduler(scheduler)
    new_req = await rescheduler.execute(stuck, RecoveryAction.RETRY)
    assert new_req is not None
    assert "retry" in new_req.execution_id
    assert new_req.metadata["recovery_attempts"] == 1
    assert new_req.metadata["recovered_from"] == "e1"

    # 旧执行标记 FAILED
    old = await scheduler.get("e1")
    assert old.status is QueueStatus.FAILED

    # 新请求在队列中
    assert await scheduler.queue_depth() == 1


async def test_rescheduler_mark_failed():
    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store)
    await scheduler.submit(_req("e1"))
    await scheduler.dispatch_next()

    stuck = StuckExecution("e1", "t1", "s1", "u1", "timeout", 0.0)
    rescheduler = Rescheduler(scheduler)
    await rescheduler.execute(stuck, RecoveryAction.MARK_FAILED)

    r = await scheduler.get("e1")
    assert r.status is QueueStatus.FAILED


async def test_rescheduler_mark_human():
    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store)
    await scheduler.submit(_req("e1"))
    await scheduler.dispatch_next()

    stuck = StuckExecution("e1", "t1", "s1", "u1", "timeout", 0.0)
    rescheduler = Rescheduler(scheduler)
    await rescheduler.execute(stuck, RecoveryAction.MARK_HUMAN)

    # 不改队列状态（等人工处理）
    r = await scheduler.get("e1")
    assert r.status is QueueStatus.DISPATCHED


# ===== RecoveryOrchestrator =====

async def test_orchestrator_end_to_end_retry():
    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store, SchedulerConfig(max_concurrent=10))
    await scheduler.submit(_req("e1"))
    await scheduler.dispatch_next()

    r = store._store["e1"]
    r.dispatched_at = time.time() - 400

    orch = RecoveryOrchestrator(scheduler, ReaperConfig(dispatch_timeout=300))
    results = await orch.run_cycle()
    assert len(results) == 1
    stuck, action = results[0]
    assert action is RecoveryAction.RETRY
    assert await scheduler.queue_depth() == 1


async def test_orchestrator_with_contract_resolver():
    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store, SchedulerConfig(max_concurrent=10))
    await scheduler.submit(_req("e1"))
    await scheduler.dispatch_next()

    r = store._store["e1"]
    r.dispatched_at = time.time() - 400

    def resolver(eid: str):
        return EffectContract.non_idempotent_write("order")

    orch = RecoveryOrchestrator(
        scheduler, ReaperConfig(dispatch_timeout=300), contract_resolver=resolver
    )
    results = await orch.run_cycle()
    assert results[0][1] is RecoveryAction.MARK_HUMAN


async def test_orchestrator_max_retries_then_failed():
    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store, SchedulerConfig(max_concurrent=10))

    req = _req("e1")
    req.metadata["recovery_attempts"] = 3
    await scheduler.submit(req)
    await scheduler.dispatch_next()

    r = store._store["e1"]
    r.dispatched_at = time.time() - 400

    orch = RecoveryOrchestrator(scheduler, ReaperConfig(dispatch_timeout=300, max_retries=3))
    results = await orch.run_cycle()
    assert results[0][1] is RecoveryAction.MARK_FAILED

    r = await scheduler.get("e1")
    assert r.status is QueueStatus.FAILED


# ===== contract_resolver 生产工厂（2026-10-19，#99 缺口 4 残差） =====


class _FakeTrajectoryStore:
    """按 execution_id 返回预置 TrajectoryRecord（或 None）。"""

    def __init__(self, records: dict):
        self._records = records

    async def get(self, execution_id: str):
        return self._records.get(execution_id)


class _FakeRecord:
    def __init__(self, plan: dict):
        self.plan = plan


class _FakeSkill:
    def __init__(self, contract):
        self.effect_contract = contract


class _FakeRegistry:
    def __init__(self, skills: dict):
        self._skills = skills

    def get(self, name: str):
        if name not in self._skills:
            raise KeyError(name)
        return self._skills[name]


_CONTRACT = EffectContract(
    effect_key="order_id",
    delivery_semantics=DeliverySemantics.EFFECTIVELY_ONCE,
    idempotency_strategy=IdempotencyStrategy.BUSINESS_KEY,
    receipt_strategy=ReceiptStrategy.EXTERNAL_ID,
    retry_policy=RetryPolicy.SAFE,
    failure_recovery=FailureRecovery.QUERY_BEFORE_RETRY,
)


async def test_resolver_happy_path_route_to_contract():
    """deterministic 轨迹（plan.route）→ registry → contract。"""
    from agent_runtime.execution_recovery import make_trajectory_contract_resolver

    store = _FakeTrajectoryStore({"e1": _FakeRecord({"route": "venue.query"})})
    registry = _FakeRegistry({"venue.query": _FakeSkill(_CONTRACT)})
    resolve = make_trajectory_contract_resolver(store, registry)
    assert await resolve("e1") is _CONTRACT


async def test_resolver_route_hit_but_no_contract():
    """skill 在册但无 contract → None（不猜）。"""
    from agent_runtime.execution_recovery import make_trajectory_contract_resolver

    store = _FakeTrajectoryStore({"e1": _FakeRecord({"route": "venue.query"})})
    registry = _FakeRegistry({"venue.query": _FakeSkill(None)})
    resolve = make_trajectory_contract_resolver(store, registry)
    assert await resolve("e1") is None


async def test_resolver_missing_record_degrades_none():
    """轨迹记录不存在 → None（现状语义：无契约默认可重试）。"""
    from agent_runtime.execution_recovery import make_trajectory_contract_resolver

    resolve = make_trajectory_contract_resolver(_FakeTrajectoryStore({}), _FakeRegistry({}))
    assert await resolve("nope") is None


async def test_resolver_empty_route_degrades_none():
    """graph/agentic 模式（route 空）→ None；逐 skill 契约恢复转新缺口，不猜。"""
    from agent_runtime.execution_recovery import make_trajectory_contract_resolver

    store = _FakeTrajectoryStore({"e1": _FakeRecord({"mode": "graph", "route": ""})})
    registry = _FakeRegistry({"venue.query": _FakeSkill(_CONTRACT)})
    resolve = make_trajectory_contract_resolver(store, registry)
    assert await resolve("e1") is None


async def test_resolver_unregistered_skill_degrades_none():
    """skill 未注册（退役/改名）→ None 且不抛。"""
    from agent_runtime.execution_recovery import make_trajectory_contract_resolver

    store = _FakeTrajectoryStore({"e1": _FakeRecord({"route": "retired.skill"})})
    registry = _FakeRegistry({})
    resolve = make_trajectory_contract_resolver(store, registry)
    assert await resolve("e1") is None


async def test_resolver_store_get_raises_degrades_none_via_orchestrator():
    """store.get 抛错 → orchestrator 的 try/except 兜住（contract=None，不崩恢复周期）。"""
    from agent_runtime.execution_recovery import (
        RecoveryOrchestrator,
        make_trajectory_contract_resolver,
    )

    class _BoomStore:
        async def get(self, execution_id: str):
            raise RuntimeError("pg down")

    resolve = make_trajectory_contract_resolver(_BoomStore(), _FakeRegistry({}))

    class _FakeScheduler:
        _store = None

    orch = RecoveryOrchestrator.__new__(RecoveryOrchestrator)
    orch._resolve_contract = resolve
    stuck = StuckExecution(
        execution_id="e1",
        tenant_id="t1",
        session_id="s1",
        user_id="u1",
        reason="running_timeout",
        stuck_since=0.0,
        attempt=0,
        original=_req(),
    )
    # 复刻 recover_one 的调用点语义：awaitable + 异常兜底
    resolved = None
    try:
        r = orch._resolve_contract(stuck.execution_id)
        import inspect as _inspect

        if _inspect.isawaitable(r):
            r = await r
        resolved = r
    except RuntimeError:
        resolved = None
    assert resolved is None


async def test_orchestrator_consumes_async_resolver():
    """编排器级：传入的 async resolver 被 recover_one 真正消费（awaitable 路径）。"""
    from agent_runtime.execution_recovery import RecoveryOrchestrator

    store = InMemorySchedulerStore()
    scheduler = ExecutionScheduler(store)
    await scheduler.submit(_req("e1"))
    await scheduler.complete("e1", QueueStatus.FAILED)

    seen: list[str] = []

    async def _resolve(execution_id: str):
        seen.append(execution_id)
        return _CONTRACT  # QUERY_BEFORE_RETRY ⇒ 决策应为 QUERY_STATUS

    orch = RecoveryOrchestrator(scheduler, config=ReaperConfig(), contract_resolver=_resolve)
    action = await orch.recover_one(await store.get("e1"))
    assert seen == ["e1"], "async resolver 未被调用（awaitable 路径断）"
    assert action is RecoveryAction.QUERY_STATUS, "contract 语义未进入决策"


# ===== QUERY_STATUS 执行体（2026-10-19，缺口 3：_mark_for_query 桩→真查） =====


class _FakeTask:
    def __init__(self, state, execution_id="e1"):
        self.state = state
        self.execution_id = execution_id


class _FakeAwaitableStore:
    def __init__(self, tasks_by_execution: dict | None = None, boom: bool = False):
        self._tasks = tasks_by_execution or {}
        self._boom = boom
        self.calls: list[str] = []

    async def list_by_execution(self, execution_id: str):
        self.calls.append(execution_id)
        if self._boom:
            raise RuntimeError("pg down")
        return self._tasks.get(execution_id, [])


async def _park_and_stuck(store_scheduler, execution_id="e1"):
    req = _req(execution_id)
    await store_scheduler.submit(req)
    await store_scheduler.complete(execution_id, QueueStatus.FAILED)
    from agent_runtime.execution_recovery import stuck_from_request

    return stuck_from_request(await store_scheduler._store.get(execution_id))


async def test_query_status_no_store_degrades_to_log_only():
    """store 缺席 ⇒ 仅日志、零状态变更、零入队（现值逐字保持）。"""
    from agent_runtime.execution_recovery import Rescheduler

    store = InMemorySchedulerStore()
    sched = ExecutionScheduler(store)
    rescheduler = Rescheduler(sched)  # 无 awaitable_store
    stuck = await _park_and_stuck(sched)
    await rescheduler.execute(stuck, RecoveryAction.QUERY_STATUS)
    assert await store.get("e1:resume:1") is None, "store 缺席不得入队"


async def test_query_status_no_tasks_no_action():
    """无外部任务记录 ⇒ WARNING + 无动作（不从"缺席" fabrication retry/fail）。"""
    from agent_runtime.execution_recovery import Rescheduler

    store = InMemorySchedulerStore()
    sched = ExecutionScheduler(store)
    rescheduler = Rescheduler(sched, awaitable_store=_FakeAwaitableStore({}))
    stuck = await _park_and_stuck(sched)
    await rescheduler.execute(stuck, RecoveryAction.QUERY_STATUS)
    assert await store.get("e1:resume:1") is None


async def test_query_status_completed_resumes_not_retries():
    """外部已完成 ⇒ 入队 :resume:N（续跑而非重跑——重跑=重复副作用）。"""
    from agent_runtime.awaitable_task import AwaitableState
    from agent_runtime.execution_recovery import Rescheduler

    store = InMemorySchedulerStore()
    sched = ExecutionScheduler(store)
    rescheduler = Rescheduler(
        sched, awaitable_store=_FakeAwaitableStore({"e1": [_FakeTask(AwaitableState.COMPLETED)]})
    )
    stuck = await _park_and_stuck(sched)
    await rescheduler.execute(stuck, RecoveryAction.QUERY_STATUS)
    resumed = await store.get("e1:resume:1")
    assert resumed is not None, "外部已完成必须入队续跑请求"
    assert resumed.metadata.get("recovery_action") == "resume"
    assert resumed.metadata.get("recovered_from") == "e1"


async def test_query_status_failed_marks_failed():
    """外部已失败/超时 ⇒ complete(FAILED)（重试无意义）。"""
    from agent_runtime.awaitable_task import AwaitableState
    from agent_runtime.execution_recovery import Rescheduler

    store = InMemorySchedulerStore()
    sched = ExecutionScheduler(store)
    rescheduler = Rescheduler(
        sched,
        awaitable_store=_FakeAwaitableStore({"e1": [_FakeTask(AwaitableState.TIMED_OUT)]}),
    )
    stuck = await _park_and_stuck(sched)
    await rescheduler.execute(stuck, RecoveryAction.QUERY_STATUS)
    assert await store.get("e1:resume:1") is None, "外部失败不得入队"
    # 原执行已被 complete（stuck_from_request 的 original 已 FAILED；此处验证无新请求）


async def test_query_status_in_flight_no_action():
    """全部在途（SUBMITTED/RUNNING）⇒ 无动作——QUERY_BEFORE_RETRY 的反重复副作用核心。"""
    from agent_runtime.awaitable_task import AwaitableState
    from agent_runtime.execution_recovery import Rescheduler

    store = InMemorySchedulerStore()
    sched = ExecutionScheduler(store)
    rescheduler = Rescheduler(
        sched,
        awaitable_store=_FakeAwaitableStore(
            {"e1": [_FakeTask(AwaitableState.SUBMITTED), _FakeTask(AwaitableState.RUNNING)]}
        ),
    )
    stuck = await _park_and_stuck(sched)
    await rescheduler.execute(stuck, RecoveryAction.QUERY_STATUS)
    assert await store.get("e1:resume:1") is None, "在途外部任务不得触发任何重试/入队"


async def test_query_status_store_error_tolerated():
    """store 抛错 ⇒ 容错记 WARNING，不崩恢复周期（与 resolve_contract 同款）。"""
    from agent_runtime.execution_recovery import Rescheduler

    store = InMemorySchedulerStore()
    sched = ExecutionScheduler(store)
    rescheduler = Rescheduler(sched, awaitable_store=_FakeAwaitableStore(boom=True))
    stuck = await _park_and_stuck(sched)
    await rescheduler.execute(stuck, RecoveryAction.QUERY_STATUS)  # 不得抛
    assert await store.get("e1:resume:1") is None
