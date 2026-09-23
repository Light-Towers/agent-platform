"""Execution Scheduler（V3-4A）：队列 + 优先级 + 公平性 + 槽位管理。

现状（v3 之前的缺口）：链路是 ``Admission → Planner → Execute``，Admission 回答
"现在允不允许开始"，不回答"哪个 Execution 由哪个 Worker 在什么时候执行"。

本模块补上：
- ``ExecutionRequest``：待调度执行请求（execution_id / tenant / priority / resource_hints）；
- ``SchedulerStore``：持久化调度队列契约（InMemory + PG）；
- ``ExecutionScheduler``：从队列按 **priority → fairness（per-tenant 已运行数少者优先）
  → FIFO** 选下一个，受全局 + per-tenant 槽位约束；
- Backpressure：队列深度超 ``queue_capacity`` 拒绝入队。

调度算法（dequeue）：
```
1. 按 priority 降序（high > normal > low）
2. 同 priority 内按 tenant 已运行数升序（少运行的 tenant 优先 → fairness）
3. 同 priority 同 tenant 内按 created_at 升序（FIFO）
4. 检查 per-tenant concurrent ≤ max_concurrent_per_tenant
5. 检查全局 concurrent ≤ max_concurrent
6. FOR UPDATE SKIP LOCKED 跳过并发已锁行
```

不自建 K8s Scheduler（Part C 红线），用 PG 做队列 + 自研轻量调度策略。
"""

from __future__ import annotations

import abc
import asyncio
import copy
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ExecutionPriority(str, Enum):
    """调度优先级。"""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"

    @property
    def weight(self) -> int:
        """排序权重（越大越优先）。"""
        return {ExecutionPriority.LOW: 0, ExecutionPriority.NORMAL: 1, ExecutionPriority.HIGH: 2}[self]


class QueueStatus(str, Enum):
    """调度队列状态机。"""

    QUEUED = "queued"  # 已入队待调度
    DISPATCHED = "dispatched"  # 已选中待分发
    RUNNING = "running"  # Worker 执行中
    COMPLETED = "completed"  # 成功完成
    FAILED = "failed"  # 失败
    CANCELLED = "cancelled"  # 已取消

    @property
    def is_terminal(self) -> bool:
        return self in {QueueStatus.COMPLETED, QueueStatus.FAILED, QueueStatus.CANCELLED}

    @property
    def occupies_slot(self) -> bool:
        """是否占用执行槽位。"""
        return self in {QueueStatus.DISPATCHED, QueueStatus.RUNNING}


@dataclass
class ExecutionRequest:
    """待调度的执行请求。"""

    execution_id: str
    tenant_id: str
    session_id: str
    user_id: str
    priority: ExecutionPriority = ExecutionPriority.NORMAL
    resource_hints: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    status: QueueStatus = QueueStatus.QUEUED
    worker_id: str | None = None
    dispatched_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "priority": self.priority.value,
            "resource_hints": self.resource_hints,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "status": self.status.value,
            "worker_id": self.worker_id,
            "dispatched_at": self.dispatched_at,
        }


@dataclass
class SchedulerConfig:
    """调度器配置。"""

    max_concurrent: int = 10  # 全局最大并发槽位
    max_concurrent_per_tenant: int = 5  # per-tenant 最大并发
    queue_capacity: int = 1000  # 队列容量（backpressure 阈值）


class QueueFull(RuntimeError):
    """队列已满（backpressure）。"""


class SchedulerStore(abc.ABC):
    """调度队列持久化契约。"""

    @abc.abstractmethod
    async def enqueue(self, req: ExecutionRequest) -> None:
        """入队（新建）。"""

    @abc.abstractmethod
    async def dequeue(self, config: SchedulerConfig) -> ExecutionRequest | None:
        """按 priority + fairness + FIFO 选下一个待调度执行，标记 DISPATCHED。

        须原子完成"选 + 标记"（PG 用 FOR UPDATE SKIP LOCKED + UPDATE 同事务）。
        """

    @abc.abstractmethod
    async def mark_running(self, execution_id: str, worker_id: str) -> None:
        """标记为 RUNNING（Worker 开始执行）。"""

    @abc.abstractmethod
    async def mark_completed(self, execution_id: str, status: QueueStatus) -> None:
        """标记终态（COMPLETED / FAILED / CANCELLED），释放槽位。"""

    @abc.abstractmethod
    async def count_running(self) -> int:
        """当前占用槽位数（DISPATCHED + RUNNING）。"""

    @abc.abstractmethod
    async def count_running_by_tenant(self, tenant_id: str) -> int:
        """per-tenant 当前占用槽位数。"""

    @abc.abstractmethod
    async def count_queued(self) -> int:
        """队列深度（QUEUED 数）。"""

    @abc.abstractmethod
    async def get(self, execution_id: str) -> ExecutionRequest | None:
        """按 execution_id 读取。"""

    @abc.abstractmethod
    async def cancel(self, execution_id: str) -> bool:
        """取消（仅 QUEUED 可取消；RUNNING 需走 control plane）。返回是否成功。"""

    @abc.abstractmethod
    async def list_overdue(
        self, dispatch_timeout: float, running_timeout: float
    ) -> list[ExecutionRequest]:
        """列出超时的 DISPATCHED / RUNNING 执行（供 Reaper 扫描）。

        - DISPATCHED 超 ``dispatch_timeout``（Worker 未 mark_running）；
        - RUNNING 超 ``running_timeout``（执行超时）。
        """


class InMemorySchedulerStore(SchedulerStore):
    """进程内调度队列（测试 / 单进程默认后端）。"""

    def __init__(self) -> None:
        self._store: dict[str, ExecutionRequest] = {}

    async def enqueue(self, req: ExecutionRequest) -> None:
        self._store[req.execution_id] = copy.deepcopy(req)

    async def dequeue(self, config: SchedulerConfig) -> ExecutionRequest | None:
        queued = [
            r
            for r in self._store.values()
            if r.status is QueueStatus.QUEUED
        ]
        if not queued:
            return None

        running_total = sum(1 for r in self._store.values() if r.status.occupies_slot)
        if running_total >= config.max_concurrent:
            return None

        tenant_running: dict[str, int] = {}
        for r in self._store.values():
            if r.status.occupies_slot:
                tenant_running[r.tenant_id] = tenant_running.get(r.tenant_id, 0) + 1

        def sort_key(r: ExecutionRequest) -> tuple[int, int, float]:
            return (
                -r.priority.weight,
                tenant_running.get(r.tenant_id, 0),
                r.created_at,
            )

        queued.sort(key=sort_key)

        for cand in queued:
            if tenant_running.get(cand.tenant_id, 0) >= config.max_concurrent_per_tenant:
                continue
            cand.status = QueueStatus.DISPATCHED
            cand.dispatched_at = time.time()
            cand.worker_id = f"worker-{uuid.uuid4().hex[:8]}"
            self._store[cand.execution_id] = copy.deepcopy(cand)
            return cand

        return None

    async def mark_running(self, execution_id: str, worker_id: str) -> None:
        r = self._store.get(execution_id)
        if r is not None and r.status is QueueStatus.DISPATCHED:
            r.status = QueueStatus.RUNNING
            r.worker_id = worker_id
            self._store[execution_id] = copy.deepcopy(r)

    async def mark_completed(self, execution_id: str, status: QueueStatus) -> None:
        r = self._store.get(execution_id)
        if r is not None and not r.status.is_terminal:
            r.status = status
            self._store[execution_id] = copy.deepcopy(r)

    async def count_running(self) -> int:
        return sum(1 for r in self._store.values() if r.status.occupies_slot)

    async def count_running_by_tenant(self, tenant_id: str) -> int:
        return sum(
            1
            for r in self._store.values()
            if r.status.occupies_slot and r.tenant_id == tenant_id
        )

    async def count_queued(self) -> int:
        return sum(1 for r in self._store.values() if r.status is QueueStatus.QUEUED)

    async def get(self, execution_id: str) -> ExecutionRequest | None:
        return self._store.get(execution_id)

    async def cancel(self, execution_id: str) -> bool:
        r = self._store.get(execution_id)
        if r is not None and r.status is QueueStatus.QUEUED:
            r.status = QueueStatus.CANCELLED
            self._store[execution_id] = copy.deepcopy(r)
            return True
        return False

    async def list_overdue(
        self, dispatch_timeout: float, running_timeout: float
    ) -> list[ExecutionRequest]:
        now = time.time()
        result = []
        for r in self._store.values():
            if r.status is QueueStatus.DISPATCHED and r.dispatched_at is not None:
                if now - r.dispatched_at > dispatch_timeout:
                    result.append(r)
            elif r.status is QueueStatus.RUNNING and r.dispatched_at is not None:
                if now - r.dispatched_at > running_timeout:
                    result.append(r)
        return result


class PgSchedulerStore(SchedulerStore):
    """PG 持久化调度队列。

    dequeue 用 ``FOR UPDATE SKIP LOCKED`` 原子选 + 标记，fairness 通过
    子查询统计 per-tenant 已运行数作为排序键实现。
    """

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def enqueue(self, req: ExecutionRequest) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO execution_queue "
                "(execution_id, tenant_id, session_id, user_id, priority, "
                " status, created_at, resource_hints, metadata) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    req.execution_id,
                    req.tenant_id,
                    req.session_id,
                    req.user_id,
                    req.priority.value,
                    QueueStatus.QUEUED.value,
                    req.created_at,
                    json.dumps(req.resource_hints),
                    json.dumps(req.metadata),
                ),
            )

    async def dequeue(self, config: SchedulerConfig) -> ExecutionRequest | None:
        async with self._pool.connection() as conn, conn.transaction():
            running_row = await conn.execute(
                "SELECT count(*) FROM execution_queue "
                "WHERE status IN (%s, %s)",
                (QueueStatus.DISPATCHED.value, QueueStatus.RUNNING.value),
            )
            count = await running_row.fetchone()
            running_total = count[0] if count else 0
            if running_total >= config.max_concurrent:
                return None

            row = await conn.execute(
                "SELECT eq.execution_id, eq.tenant_id, eq.session_id, eq.user_id, "
                "       eq.priority, eq.created_at, eq.resource_hints, eq.metadata "
                "FROM execution_queue eq "
                "LEFT JOIN LATERAL ("
                "  SELECT count(*) AS tenant_running FROM execution_queue "
                "  WHERE tenant_id = eq.tenant_id "
                "    AND status IN (%s, %s)"
                ") tr ON true "
                "WHERE eq.status = %s "
                "  AND tr.tenant_running < %s "
                "ORDER BY "
                "  CASE eq.priority WHEN 'high' THEN 2 WHEN 'normal' THEN 1 ELSE 0 END DESC, "
                "  tr.tenant_running ASC, "
                "  eq.created_at ASC "
                "LIMIT 1 FOR UPDATE SKIP LOCKED",
                (
                    QueueStatus.DISPATCHED.value,
                    QueueStatus.RUNNING.value,
                    QueueStatus.QUEUED.value,
                    config.max_concurrent_per_tenant,
                ),
            )
            r = await row.fetchone()
            if not r:
                return None

            execution_id = r[0]
            worker_id = f"worker-{uuid.uuid4().hex[:8]}"
            now = time.time()
            await conn.execute(
                "UPDATE execution_queue SET status = %s, dispatched_at = %s, "
                "worker_id = %s WHERE execution_id = %s",
                (QueueStatus.DISPATCHED.value, now, worker_id, execution_id),
            )

            return ExecutionRequest(
                execution_id=execution_id,
                tenant_id=r[1],
                session_id=r[2],
                user_id=r[3],
                priority=ExecutionPriority(r[4]),
                created_at=r[5],
                resource_hints=json.loads(r[6]) if r[6] else {},
                metadata=json.loads(r[7]) if r[7] else {},
                status=QueueStatus.DISPATCHED,
                worker_id=worker_id,
                dispatched_at=now,
            )

    async def mark_running(self, execution_id: str, worker_id: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE execution_queue SET status = %s, worker_id = %s "
                "WHERE execution_id = %s AND status = %s",
                (QueueStatus.RUNNING.value, worker_id, execution_id, QueueStatus.DISPATCHED.value),
            )

    async def mark_completed(self, execution_id: str, status: QueueStatus) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE execution_queue SET status = %s "
                "WHERE execution_id = %s AND status NOT IN (%s, %s, %s)",
                (
                    status.value,
                    execution_id,
                    QueueStatus.COMPLETED.value,
                    QueueStatus.FAILED.value,
                    QueueStatus.CANCELLED.value,
                ),
            )

    async def count_running(self) -> int:
        async with self._pool.connection() as conn:
            row = await conn.execute(
                "SELECT count(*) FROM execution_queue WHERE status IN (%s, %s)",
                (QueueStatus.DISPATCHED.value, QueueStatus.RUNNING.value),
            )
            r = await row.fetchone()
            return r[0] if r else 0

    async def count_running_by_tenant(self, tenant_id: str) -> int:
        async with self._pool.connection() as conn:
            row = await conn.execute(
                "SELECT count(*) FROM execution_queue "
                "WHERE tenant_id = %s AND status IN (%s, %s)",
                (tenant_id, QueueStatus.DISPATCHED.value, QueueStatus.RUNNING.value),
            )
            r = await row.fetchone()
            return r[0] if r else 0

    async def count_queued(self) -> int:
        async with self._pool.connection() as conn:
            row = await conn.execute(
                "SELECT count(*) FROM execution_queue WHERE status = %s",
                (QueueStatus.QUEUED.value,),
            )
            r = await row.fetchone()
            return r[0] if r else 0

    async def get(self, execution_id: str) -> ExecutionRequest | None:
        async with self._pool.connection() as conn:
            row = await conn.execute(
                "SELECT execution_id, tenant_id, session_id, user_id, priority, "
                "       created_at, resource_hints, metadata, status, worker_id, dispatched_at "
                "FROM execution_queue WHERE execution_id = %s",
                (execution_id,),
            )
            r = await row.fetchone()
            if not r:
                return None
            return ExecutionRequest(
                execution_id=r[0],
                tenant_id=r[1],
                session_id=r[2],
                user_id=r[3],
                priority=ExecutionPriority(r[4]),
                created_at=r[5],
                resource_hints=json.loads(r[6]) if r[6] else {},
                metadata=json.loads(r[7]) if r[7] else {},
                status=QueueStatus(r[8]),
                worker_id=r[9],
                dispatched_at=r[10],
            )

    async def cancel(self, execution_id: str) -> bool:
        async with self._pool.connection() as conn:
            result = await conn.execute(
                "UPDATE execution_queue SET status = %s "
                "WHERE execution_id = %s AND status = %s",
                (QueueStatus.CANCELLED.value, execution_id, QueueStatus.QUEUED.value),
            )
            return (result.rowcount if hasattr(result, "rowcount") else 0) > 0

    async def list_overdue(
        self, dispatch_timeout: float, running_timeout: float
    ) -> list[ExecutionRequest]:
        now = time.time()
        async with self._pool.connection() as conn:
            row = await conn.execute(
                "SELECT execution_id, tenant_id, session_id, user_id, priority, "
                "       created_at, resource_hints, metadata, status, worker_id, dispatched_at "
                "FROM execution_queue "
                "WHERE (status = %s AND dispatched_at IS NOT NULL "
                "       AND %s - dispatched_at > %s) "
                "   OR (status = %s AND dispatched_at IS NOT NULL "
                "       AND %s - dispatched_at > %s)",
                (
                    QueueStatus.DISPATCHED.value, now, dispatch_timeout,
                    QueueStatus.RUNNING.value, now, running_timeout,
                ),
            )
            rows = await row.fetchall()
            return [
                ExecutionRequest(
                    execution_id=r[0],
                    tenant_id=r[1],
                    session_id=r[2],
                    user_id=r[3],
                    priority=ExecutionPriority(r[4]),
                    created_at=r[5],
                    resource_hints=json.loads(r[6]) if r[6] else {},
                    metadata=json.loads(r[7]) if r[7] else {},
                    status=QueueStatus(r[8]),
                    worker_id=r[9],
                    dispatched_at=r[10],
                )
                for r in rows
            ]


class ExecutionScheduler:
    """Execution Scheduler：队列 + 优先级 + 公平性 + 槽位管理。"""

    def __init__(self, store: SchedulerStore, config: SchedulerConfig | None = None) -> None:
        self._store = store
        self._config = config or SchedulerConfig()

    async def submit(self, req: ExecutionRequest) -> None:
        """入队（带 backpressure 检查）。队列满时抛 QueueFull。"""
        depth = await self._store.count_queued()
        if depth >= self._config.queue_capacity:
            raise QueueFull(
                f"调度队列已满（depth={depth} >= capacity={self._config.queue_capacity}）"
            )
        await self._store.enqueue(req)

    async def dispatch_next(self) -> ExecutionRequest | None:
        """选下一个待调度执行并标记 DISPATCHED。无可用时返回 None。"""
        return await self._store.dequeue(self._config)

    async def mark_running(self, execution_id: str, worker_id: str) -> None:
        """Worker 开始执行时标记 RUNNING。"""
        await self._store.mark_running(execution_id, worker_id)

    async def complete(self, execution_id: str, status: QueueStatus) -> None:
        """执行完成（COMPLETED / FAILED / CANCELLED），释放槽位。"""
        await self._store.mark_completed(execution_id, status)

    async def cancel(self, execution_id: str) -> bool:
        """取消排队中的执行。RUNNING 需走 control plane（V3-5B）。"""
        return await self._store.cancel(execution_id)

    async def queue_depth(self) -> int:
        """队列深度（QUEUED 数，backpressure 监控）。"""
        return await self._store.count_queued()

    async def running_count(self) -> int:
        """当前占用槽位数。"""
        return await self._store.count_running()

    async def get(self, execution_id: str) -> ExecutionRequest | None:
        """查询执行请求状态。"""
        return await self._store.get(execution_id)

    async def list_overdue(
        self, dispatch_timeout: float, running_timeout: float
    ) -> list[ExecutionRequest]:
        """列出超时的 DISPATCHED / RUNNING 执行（供 Reaper 扫描）。"""
        return await self._store.list_overdue(dispatch_timeout, running_timeout)


class SchedulerReaper:
    """回收 lease 已失效的执行：标记 FAILED + 释放 slot（V3 Phase 3）。

    核心约束：**只回收 lease 已失效的执行，不依据 wall-clock timeout 判定执行已终止。**

    ``list_overdue()`` 给出超时候选，``ownership_store.get_owner()`` 做安全门控——
    lease 仍有效（owner 非 None）则跳过（Worker 仍在跑），lease 已失效（owner 为 None）
    才标记 FAILED。这避免 Reaper 与活 Worker 竞态导致 slot 双重占用。

    与 V2 Lease/Fencing 的关系：复用 V2 已有的 lease 过期 + generation fencing，
    不重新设计恢复语义。Reaper 是 Scheduler 层的"lease 过期清扫器"。
    """

    def __init__(
        self,
        scheduler: ExecutionScheduler,
        ownership_store: Any,
        *,
        interval_s: float = 30.0,
        dispatch_timeout: float = 60.0,
        running_timeout: float = 300.0,
    ) -> None:
        self._scheduler = scheduler
        self._ownership = ownership_store
        self._interval_s = interval_s
        self._dispatch_timeout = dispatch_timeout
        self._running_timeout = running_timeout
        self._stopped = False
        self._task: Any = None

    async def run(self) -> None:
        """周期扫描超时执行，对 lease 已失效的标记 FAILED + 释放 slot。"""
        import logging

        logger = logging.getLogger(__name__)
        while not self._stopped:
            try:
                overdue = await self._scheduler.list_overdue(
                    self._dispatch_timeout, self._running_timeout
                )
                for req in overdue:
                    # 安全门控：确认 lease 确实已失效（get_owner 返回 None = 无/过期）
                    owner = await self._ownership.get_owner(req.execution_id)
                    if owner is not None:
                        continue  # lease 仍有效，Worker 可能还在跑，跳过
                    # lease 已失效 → 安全标记 FAILED + 释放 slot
                    await self._scheduler.complete(req.execution_id, QueueStatus.FAILED)
                    logger.warning(
                        "reaper: execution %s lease expired, marked FAILED",
                        req.execution_id,
                    )
            except Exception:
                logger.debug("reaper scan failed", exc_info=True)
            await asyncio.sleep(self._interval_s)

    def start(self) -> None:
        """启动 Reaper 后台协程。"""
        import asyncio

        self._task = asyncio.ensure_future(self.run())

    async def stop(self) -> None:
        """停止 Reaper（优雅关闭）。"""
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


__all__ = [
    "ExecutionPriority",
    "QueueStatus",
    "ExecutionRequest",
    "SchedulerConfig",
    "QueueFull",
    "SchedulerStore",
    "InMemorySchedulerStore",
    "PgSchedulerStore",
    "ExecutionScheduler",
    "SchedulerReaper",
]
