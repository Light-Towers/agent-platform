"""Execution Recovery / Reaper / Reschedule（V3-4B）。

.. note::
   **STATUS: WIRED（2026-10-15，默认关）** – 两个生产消费方：
   ``SchedulerReaper``（lease 失效后按契约决策而非无条件 FAILED）与
   ``ControlPlane.recover``（人工触发单次恢复）。均由
   ``SCHEDULER_RECOVERY_ENABLED`` 门控，**默认 False**；关闭时 Reaper 逐字保持
   旧行为（只标 FAILED + 释放 slot）。
   边界（2026-10-19 更新，#99）：``contract_resolver`` **已接生产**——
   ``make_trajectory_contract_resolver`` 读轨迹取 ``plan.route`` 经 registry
   查契约；四类落空（无记录 / route 空 / skill 未注册 / 无 contract）降级 None
   ⇒ 决策退化为「无契约默认可重试」。graph/agentic 多 skill 模式的逐 skill
   契约恢复决策**仍缺**（转新缺口，本模块不猜）。
   兄弟模块 ``payload_externalization``（由 ``agent_server`` 的
   ``_build_payload_externalizer`` 构造并注进 checkpoint 链路）与 ``human_task``
   （``main`` 装 ``HumanTaskStore`` → ``protocol.delegate`` 按 ``kind="human"`` 分派）
   已于 2026-10-15 接线，**接线 ≠ 默认启用**：payload 侧受
   ``payload_externalization_enabled``（默认 False）门控，human_task 侧状态机推进
   依赖 scheduler 开关。
   （此前状态为 NOT WIRED，P1-7 审计披露 2026-09-24）

补 V3-4A 留的恢复侧：执行超时 / Worker 死亡 / lease 过期后，如何把 stuck execution
拉回正轨。

三部件：
- ``Reaper``：定期扫描 SchedulerStore 找超时 DISPATCHED/RUNNING，产出 ``StuckExecution``；
- ``RecoveryManager``：按 Effect Contract 决策恢复动作（retry / query / fail / manual）；
- ``Rescheduler``：执行恢复动作——retry 重新入队，query 查外部状态，fail 标记失败。

调度闭环：
```
Reaper.scan() → [StuckExecution]
    ↓
RecoveryManager.decide(stuck, contract) → RecoveryAction
    ↓
Rescheduler.execute(stuck, action) → 重新入队 / 标记失败 / 标记人工
```

重试次数追踪：用 ExecutionRequest.metadata["recovery_attempts"] 累计，
超 ``max_retries`` 后强制 MARK_FAILED（无论 contract 如何）。
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from agent_runtime.effect_contract import (
    EffectContract,
    FailureRecovery,
)
from agent_runtime.execution_scheduler import (
    ExecutionPriority,
    ExecutionRequest,
    ExecutionScheduler,
    QueueStatus,
    SchedulerStore,
)

logger = logging.getLogger(__name__)


class RecoveryAction(str, Enum):
    """恢复动作（Reaper → Recovery → Rescheduler 的决策输出）。"""

    RETRY = "retry"  # 重新入队重试
    QUERY_STATUS = "query_status"  # 查询外部系统状态再决定
    MARK_FAILED = "mark_failed"  # 标记失败
    MARK_HUMAN = "mark_human"  # 标记需人工介入


@dataclass
class StuckExecution:
    """超时 / stuck 的执行（Reaper 产出）。"""

    execution_id: str
    tenant_id: str
    session_id: str
    user_id: str
    reason: str  # "dispatch_timeout" / "running_timeout"
    stuck_since: float  # 卡住的时间戳（dispatched_at）
    attempt: int = 0  # 当前重试次数
    original: ExecutionRequest | None = None  # 原始请求（供 reschedule 复用字段）


@dataclass
class ReaperConfig:
    """Reaper 配置。"""

    dispatch_timeout: float = 300.0  # DISPATCHED 超时（Worker 未 mark_running）
    running_timeout: float = 1800.0  # RUNNING 超时（执行超时）
    max_retries: int = 3  # 最大重试次数


def stuck_from_request(req: ExecutionRequest) -> StuckExecution:
    """从调度请求构造 ``StuckExecution``。

    ``Reaper.scan``（自己扫）与 ``RecoveryOrchestrator.recover_one``（调用方已扫并已
    做完安全门控）共用这一份口径，避免两处各写一遍 reason/attempt 推导而漂移。
    """
    return StuckExecution(
        execution_id=req.execution_id,
        tenant_id=req.tenant_id,
        session_id=req.session_id,
        user_id=req.user_id,
        reason=(
            "dispatch_timeout"
            if req.status is QueueStatus.DISPATCHED
            else "running_timeout"
        ),
        stuck_since=req.dispatched_at or req.created_at,
        attempt=int(req.metadata.get("recovery_attempts", 0)),
        original=req,
    )


class Reaper:
    """扫描超时 / stuck 的执行。"""

    def __init__(self, store: SchedulerStore, config: ReaperConfig | None = None) -> None:
        self._store = store
        self._config = config or ReaperConfig()

    async def scan(self) -> list[StuckExecution]:
        """扫出所有超时执行。"""
        overdue = await self._store.list_overdue(
            self._config.dispatch_timeout, self._config.running_timeout
        )
        return [stuck_from_request(req) for req in overdue]


class RecoveryManager:
    """按 Effect Contract 决策恢复动作。"""

    def __init__(self, max_retries: int = 3) -> None:
        self._max_retries = max_retries

    def decide(
        self, stuck: StuckExecution, contract: EffectContract | None
    ) -> RecoveryAction:
        """据重试次数 + Effect Contract 决策恢复动作。

        - 重试次数超限 → ``MARK_FAILED``；
        - contract is None → ``RETRY``（保持 v2 语义：无契约默认可重试）；
        - 否则按 ``contract.failure_recovery`` 映射。
        """
        if stuck.attempt >= self._max_retries:
            return RecoveryAction.MARK_FAILED

        if contract is None:
            return RecoveryAction.RETRY

        mapping = {
            FailureRecovery.RETRY_SAFE: RecoveryAction.RETRY,
            FailureRecovery.QUERY_BEFORE_RETRY: RecoveryAction.QUERY_STATUS,
            FailureRecovery.NO_RETRY: RecoveryAction.MARK_FAILED,
            FailureRecovery.MANUAL: RecoveryAction.MARK_HUMAN,
        }
        return mapping.get(contract.failure_recovery, RecoveryAction.MARK_FAILED)


class Rescheduler:
    """执行恢复动作。"""

    def __init__(self, scheduler: ExecutionScheduler) -> None:
        self._scheduler = scheduler

    async def execute(
        self, stuck: StuckExecution, action: RecoveryAction
    ) -> ExecutionRequest | None:
        """执行恢复动作。RETRY 返回新入队的请求；其他返回 None。"""
        if action is RecoveryAction.RETRY:
            return await self._retry(stuck)
        if action is RecoveryAction.QUERY_STATUS:
            await self._mark_for_query(stuck)
            return None
        if action is RecoveryAction.MARK_FAILED:
            await self._scheduler.complete(stuck.execution_id, QueueStatus.FAILED)
            logger.info(
                "recovery mark_failed execution=%s reason=%s attempt=%s",
                stuck.execution_id, stuck.reason, stuck.attempt,
            )
            return None
        if action is RecoveryAction.MARK_HUMAN:
            await self._mark_human(stuck)
            return None
        return None

    async def _retry(self, stuck: StuckExecution) -> ExecutionRequest | None:
        """标记旧执行 FAILED + 重新入队新请求（attempt + 1）。"""
        await self._scheduler.complete(stuck.execution_id, QueueStatus.FAILED)

        orig = stuck.original
        new_id = f"{stuck.execution_id}:retry:{stuck.attempt + 1}"
        new_metadata = dict(orig.metadata) if orig else {}
        new_metadata["recovery_attempts"] = stuck.attempt + 1
        new_metadata["recovered_from"] = stuck.execution_id
        new_metadata["recovery_reason"] = stuck.reason

        new_req = ExecutionRequest(
            execution_id=new_id,
            tenant_id=stuck.tenant_id,
            session_id=stuck.session_id,
            user_id=stuck.user_id,
            priority=orig.priority if orig else ExecutionPriority.NORMAL,
            resource_hints=dict(orig.resource_hints) if orig else {},
            metadata=new_metadata,
        )
        try:
            await self._scheduler.submit(new_req)
            logger.info(
                "recovery retry execution=%s → %s attempt=%s",
                stuck.execution_id, new_id, stuck.attempt + 1,
            )
            return new_req
        except Exception:
            logger.warning(
                "recovery retry failed execution=%s", stuck.execution_id, exc_info=True
            )
            return None

    async def _mark_for_query(self, stuck: StuckExecution) -> None:
        """标记需查询外部状态（不改队列状态，由外部 resolver 处理）。"""
        logger.info(
            "recovery query_status execution=%s reason=%s",
            stuck.execution_id, stuck.reason,
        )

    async def _mark_human(self, stuck: StuckExecution) -> None:
        """标记需人工介入（改 metadata，不改队列状态）。"""
        logger.info(
            "recovery mark_human execution=%s reason=%s",
            stuck.execution_id, stuck.reason,
        )


class RecoveryOrchestrator:
    """Reaper + Recovery + Rescheduler 编排器。

    一次 ``run_cycle`` 完成扫描 → 决策 → 执行全流程，供定时任务 / 事件触发调用。
    """

    def __init__(
        self,
        scheduler: ExecutionScheduler,
        config: ReaperConfig | None = None,
        contract_resolver: Any = None,
    ) -> None:
        self._scheduler = scheduler
        self._config = config or ReaperConfig()
        self._reaper = Reaper(scheduler._store, self._config)
        self._recovery = RecoveryManager(self._config.max_retries)
        self._rescheduler = Rescheduler(scheduler)
        # contract_resolver: (execution_id) -> EffectContract | None
        self._resolve_contract = contract_resolver or (lambda _eid: None)

    async def recover_one(self, req: ExecutionRequest) -> RecoveryAction:
        """对**单个**执行做决策 + 执行；不扫描、不做 lease 门控。

        给「已自行完成安全门控」的调用方用：``SchedulerReaper`` 先确认 lease 失效再调它，
        ``ControlPlane.recover`` 由人工触发。``run_cycle`` 才是自己扫 + 自己决策的定时形态。
        """
        stuck = stuck_from_request(req)
        contract = None
        try:
            resolved = self._resolve_contract(stuck.execution_id)
            # 2026-10-19（#99）：生产 resolver 读 trajectory store（async）⇒ 调用点
            # 兼awaitable；同步 resolver（测试/内存态）行为不变。
            if inspect.isawaitable(resolved):
                resolved = await resolved
            contract = resolved
        except Exception:
            logger.warning(
                "contract resolve failed execution=%s", stuck.execution_id, exc_info=True
            )
        action = self._recovery.decide(stuck, contract)
        await self._rescheduler.execute(stuck, action)
        return action

    async def run_cycle(self) -> list[tuple[StuckExecution, RecoveryAction]]:
        """执行一次恢复周期：扫描 → 决策 → 执行。返回决策记录（审计）。"""
        stuck_list = await self._reaper.scan()
        results: list[tuple[StuckExecution, RecoveryAction]] = []
        for stuck in stuck_list:
            contract = None
            try:
                contract = self._resolve_contract(stuck.execution_id)
            except Exception:
                logger.warning(
                    "contract resolve failed execution=%s", stuck.execution_id, exc_info=True
                )
            action = self._recovery.decide(stuck, contract)
            await self._rescheduler.execute(stuck, action)
            results.append((stuck, action))
        return results


def make_trajectory_contract_resolver(trajectory_store: Any, registry: Any):
    """生产 contract_resolver：execution_id → EffectContract（2026-10-19，#99）。

    数据链（均为既有件，不新造）：``trajectory_store.get(execution_id)`` →
    ``TrajectoryRecord.plan``（序列化 ``Plan``）→ deterministic 模式
    ``plan["route"]`` = skill 名 → ``registry.get(route).effect_contract``。

    **四类落空一律返回 None**——即保持「无契约默认可重试」的现状语义，
    不静默改判：
    1. 轨迹记录不存在（执行未落轨迹 / store 未装配）；
    2. ``route`` 为空（graph / agentic 多 skill 模式——逐 skill 契约的恢复
       决策需独立设计，转新缺口，本工厂不猜）；
    3. skill 未注册（退役 / 改名）；
    4. skill 无 contract（未声明）。

    store / registry 经**参数**注入（不 import 具体实现）⇒ 可单测、不引新依赖边。
    返回 async 函数（store.get 是 async）；``RecoveryOrchestrator.recover_one``
    的调用点兼awaitable（同步 resolver 行为不变）。
    """

    async def _resolve(execution_id: str):
        record = await trajectory_store.get(execution_id)
        if record is None:
            return None
        route = (getattr(record, "plan", None) or {}).get("route") or ""
        if not route:
            return None
        from agent_runtime.skills.registry import SkillNotFoundError

        try:
            skill = registry.get(route)
        except (SkillNotFoundError, KeyError):
            # SkillNotFoundError：真实 registry 的未注册口径；KeyError：内存 test
            # double 的口径。二者都归「未注册」——降级 None，不静默改判。
            logger.warning("contract resolve: skill not registered route=%s", route)
            return None
        return getattr(skill, "effect_contract", None)

    return _resolve


__all__ = [
    "RecoveryAction",
    "StuckExecution",
    "stuck_from_request",
    "ReaperConfig",
    "Reaper",
    "RecoveryManager",
    "Rescheduler",
    "RecoveryOrchestrator",
    "make_trajectory_contract_resolver",
]
