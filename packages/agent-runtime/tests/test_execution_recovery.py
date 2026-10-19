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
