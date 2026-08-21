"""Admission 前移为所有 Planner 的统一入口（§9.2 / Phase E：Admission 与 execution ownership 解耦）。

设计要点（与现有 ``admission.AdmissionQueue`` 解耦为「控制器协议」）：
- 本模块定义 ``AdmissionController`` 协议（enqueue / wait_for_admit / mark_completed）
  与 ``Planner`` 协议（plan / execute），二者均框架无关；真实实现可为 PG 队列
  （``AdmissionQueue``）或测试用内存控制器。
- ``run_admitted`` 把「准入 → 规划 → 执行 → 释放容量」串成单一入口：
  无论 deterministic / graph / agentic / workflow 哪种 Planner，**都必须先过 Admission**
  （架构不变量：Admission 是 Runtime 入口治理，不是某个 Planner 的私货）。
- deepagents 等外部 agent 框架只应作为 Planner 的「实现」，不应自带第二套准入/限流。
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

from shared_schemas import Priority

from agent_runtime.planner.durability import new_execution_id
from agent_runtime.schemas import (
    ADMISSION_ADMITTED,
    ADMISSION_QUEUED,
    ADMISSION_REJECTED,
    AdmissionDecision,
)


class AdmissionRejected(Exception):
    """请求被准入拒绝（限流 / 排队超时 / 容量耗尽）。"""

    def __init__(self, decision: AdmissionDecision) -> None:
        self.decision = decision
        super().__init__(f"admission rejected: {decision.reason}")


class AdmissionController(Protocol):
    async def enqueue(
        self, request_id: str, session_id: str, user_id: str, priority: Priority = "normal"
    ) -> AdmissionDecision: ...

    async def wait_for_admit(self, request_id: str) -> AdmissionDecision: ...

    async def mark_completed(self, request_id: str) -> None: ...


class Planner(Protocol):
    async def plan(self, query: str, runtime: Any, **kwargs: Any) -> Any: ...

    async def execute(self, plan: Any, runtime: Any, **kwargs: Any) -> Any: ...


async def run_admitted(
    controller: AdmissionController | None,
    planner: Planner,
    runtime: Any,
    query: str,
    *,
    session_id: str,
    user_id: str,
    priority: Priority = "normal",
    **kwargs: Any,
) -> Any:
    """统一入口：先经 Admission，再 plan + execute。

    ``controller`` 为 None（如未配置 DB）时跳过准入，直接 plan/execute
    （与 ``AdmissionQueue`` 默认 disabled 语义一致）。

    排队命中时阻塞等待补位；被拒（含超时）抛 ``AdmissionRejected``。
    无论执行成功/失败，均在 finally 中 ``mark_completed`` 释放容量。
    """
    if controller is None:
        plan = await planner.plan(query, runtime, **kwargs)
        return await planner.execute(plan, runtime, **kwargs)

    request_id = new_execution_id()
    try:
        decision = await controller.enqueue(request_id, session_id, user_id, priority)
        if decision.status == ADMISSION_REJECTED:
            raise AdmissionRejected(decision)
        if decision.status == ADMISSION_QUEUED:
            decision = await controller.wait_for_admit(request_id)
            if decision.status != ADMISSION_ADMITTED:
                raise AdmissionRejected(decision)
        plan = await planner.plan(query, runtime, **kwargs)
        return await planner.execute(plan, runtime, **kwargs)
    finally:
        # 无论准入/规划/执行哪一步失败（含排队超时拒绝），都释放容量；
        # 排队超时被拒的请求仍滞留 _queued，需经 mark_completed 显式移出。
        await controller.mark_completed(request_id)


class InMemoryAdmissionController:
    """测试/无 PG 场景的准入控制器：容量内直接 admitted，超出排队，mark_completed 补位。

    不跨进程、不持久化；仅用于本地验证 ``run_admitted`` 统一入口语义。
    """

    def __init__(self, capacity: int = 1, timeout_s: float = 0.0) -> None:
        self._capacity = capacity
        self._timeout_s = timeout_s
        self._active = 0
        self._queued: list[tuple[str, str, str, Priority]] = []

    async def enqueue(
        self, request_id: str, session_id: str, user_id: str, priority: Priority = "normal"
    ) -> AdmissionDecision:
        if self._active < self._capacity:
            self._active += 1
            return AdmissionDecision(status=ADMISSION_ADMITTED, priority=priority)
        self._queued.append((request_id, session_id, user_id, priority))
        return AdmissionDecision(status=ADMISSION_QUEUED, priority=priority)

    async def wait_for_admit(self, request_id: str) -> AdmissionDecision:
        try:
            await asyncio.wait_for(
                self._wait_promoted(request_id), timeout=self._timeout_s or 0.05
            )
            return AdmissionDecision(status=ADMISSION_ADMITTED, priority="normal")
        except asyncio.TimeoutError:
            return AdmissionDecision(
                status=ADMISSION_REJECTED, priority="normal", reason="ADMISSION_TIMEOUT"
            )

    async def _wait_promoted(self, request_id: str) -> None:
        while any(q[0] == request_id for q in self._queued):
            await asyncio.sleep(0.005)

    async def mark_completed(self, request_id: str) -> None:
        # 仍在排队（含排队超时拒绝）的请求：直接移出队列，不占用 active 容量
        queued_idx = next(
            (i for i, q in enumerate(self._queued) if q[0] == request_id), None
        )
        if queued_idx is not None:
            self._queued.pop(queued_idx)
            return
        # 已准入：释放 active 容量，并补位唤醒下一个排队请求
        self._active = max(0, self._active - 1)
        if self._queued:
            self._queued.pop(0)
            self._active += 1  # 补位唤醒下一个
