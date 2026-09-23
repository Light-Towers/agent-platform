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
import logging
from typing import Any, Protocol

from shared_schemas import Priority

logger = logging.getLogger(__name__)

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


class PgAdmissionController:
    """PG 持久化准入控制器（§20.2 + §20.1 跨进程唤醒）。

    设计遵循 §20 生产级约束：
    - C1: slot 抢占原子 CAS（单条 INSERT ... WHERE count < capacity RETURNING）
    - C2: PG = 事实源，LISTEN/NOTIFY 仅作唤醒，polling reconcile 兜底
    - C3: admission_slots 行级事实 + TTL，非全局 counter
    - C4: 生产模式由上层装配时校验 pool 非空（fail fast）
    - C5: wait_for_admit 轮询 + 可选 LISTEN，NOTIFY 丢失不影响正确性

    表结构 admission_slots:
    - slot_key TEXT PK（随机生成，如 uuid）
    - execution_id TEXT UNIQUE（关联请求）
    - owner TEXT（持有者标识）
    - acquired_at TIMESTAMPTZ
    - expires_at TIMESTAMPTZ（TTL 自动过期，防 Pod crash 卡槽）

    容量限制：单条 SQL 原子检查 COUNT(*) + 插入，PG 串行化保证无竞态。
    """

    def __init__(
        self,
        pool: Any,
        *,
        capacity: int = 100,
        timeout_s: float = 30.0,
        slot_ttl_s: float = 300.0,
        notify_channel: str = "admission_vacancy",
        poll_interval: float = 0.05,
    ) -> None:
        self._pool = pool
        self._capacity = capacity
        self._timeout_s = timeout_s
        self._slot_ttl_s = slot_ttl_s
        self._notify_channel = notify_channel
        self._poll_interval = poll_interval

    async def _try_acquire_slot(self, request_id: str, owner: str) -> bool:
        """CAS 抢占一个 admission slot（C1）。

        单条 SQL：在活跃槽位数 < capacity 时，插入新槽位并返回 slot_key。
        使用 COUNT(*) + INSERT 原子性，PG 事务串行化保证并发安全。
        """
        import uuid
        slot_key = uuid.uuid4().hex
        sql = (
            "INSERT INTO admission_slots (slot_key, execution_id, owner, acquired_at, expires_at) "
            "SELECT %s, %s, %s, now(), now() + (%s || ' seconds')::interval "
            "WHERE (SELECT count(*) FROM admission_slots WHERE expires_at > now()) < %s "
            "RETURNING slot_key"
        )
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql, (slot_key, request_id, owner, str(self._slot_ttl_s), self._capacity))
            row = await cur.fetchone()
        return row is not None

    async def _reap_expired_slots(self) -> int:
        """清理过期槽位（TTL 自动过期），返回清理数量。"""
        sql = "DELETE FROM admission_slots WHERE expires_at <= now()"
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql)
            # rowcount may not be available on all psycopg versions
            return cur.rowcount if hasattr(cur, "rowcount") and cur.rowcount is not None else 0

    async def enqueue(
        self,
        request_id: str,
        session_id: str,
        user_id: str,
        priority: Priority = "normal",
    ) -> AdmissionDecision:
        """请求入队/准入：CAS 抢占 slot。

        - 成功 → ADMISSION_ADMITTED
        - 失败（已满）→ ADMISSION_QUEUED（需调用 wait_for_admit）
        """
        owner = f"{session_id}:{user_id}"
        if await self._try_acquire_slot(request_id, owner):
            return AdmissionDecision(status=ADMISSION_ADMITTED, priority=priority)
        return AdmissionDecision(status=ADMISSION_QUEUED, priority=priority)

    async def wait_for_admit(self, request_id: str) -> AdmissionDecision:
        """阻塞等待 admission 调度（轮询 + 可选 LISTEN 唤醒，C2 + C5）。

        循环：
        1. 尝试 CAS 抢占 slot
        2. 成功 → ADMISSION_ADMITTED
        3. 超时 → ADMISSION_REJECTED
        4. 否则：等待 NOTIFY 或 polling interval，再重试
        """
        import time
        deadline = time.monotonic() + self._timeout_s
        owner = ""  # 在 wait_for_admit 阶段无 session/user 信息，仅用 execution_id 关联

        # 尝试建立 LISTEN 连接用于低延迟唤醒（可选，失败不影响正确性）
        listen_task = None
        stop_event = None
        notified = asyncio.Event()

        async def _listen() -> None:
            sql_listen = f"LISTEN {self._notify_channel}"
            try:
                async with self._pool.connection() as conn:
                    await conn.execute(sql_listen)
                    async for notify in conn.notifies():
                        if notify.channel == self._notify_channel:
                            notified.set()
                        if stop_event is not None and stop_event.is_set():
                            break
            except Exception:
                # LISTEN 失败不影响正确性，回退纯轮询
                pass

        listen_task = asyncio.create_task(_listen())
        stop_event = asyncio.Event()

        try:
            while True:
                if await self._try_acquire_slot(request_id, owner):
                    return AdmissionDecision(status=ADMISSION_ADMITTED, priority="normal")

                if time.monotonic() >= deadline:
                    return AdmissionDecision(
                        status=ADMISSION_REJECTED, priority="normal", reason="ADMISSION_TIMEOUT"
                    )

                # 等待 NOTIFY 或 polling interval（二者取最先到达，C2 兜底）
                notified.clear()
                try:
                    await asyncio.wait_for(notified.wait(), timeout=self._poll_interval)
                except asyncio.TimeoutError:
                    pass  # 轮询间隔到达，继续循环重试

        finally:
            stop_event.set()
            if listen_task is not None:
                listen_task.cancel()
                try:
                    await listen_task
                except (asyncio.CancelledError, Exception):
                    pass

    async def mark_completed(self, request_id: str) -> None:
        """标记请求完成：释放 slot 并发 NOTIFY 唤醒等待者（C2）。"""
        sql = "DELETE FROM admission_slots WHERE execution_id = %s"
        async with self._pool.connection() as conn:
            await conn.execute(sql, (request_id,))
            try:
                await conn.execute(f"NOTIFY {self._notify_channel}")
            except Exception:
                logger.warning("NOTIFY %s 发送失败", self._notify_channel, exc_info=True)

    async def recover_on_startup(self) -> int:
        """启动恢复：清理所有过期/残留槽位，返回清理数量。"""
        return await self._reap_expired_slots()
