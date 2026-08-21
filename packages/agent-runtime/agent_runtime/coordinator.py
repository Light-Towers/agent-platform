"""会话并发协调器：同 session 串行 / 异 session 并发。

**部署语义（架构审核 P0 明确）**：``SessionCoordinator`` 是 **process-local** 协调器——
``_active/_queues/_conditions/_cancelled`` 均为 asyncio 进程内状态，仅保证**单进程实例**
下的「同 session 串行、异 session 并发」。多 worker（uvicorn workers>1）或多副本
（K8s replicas>1）部署下该保证不成立：同 session 请求可能落在不同进程并行执行，
而 checkpoint 已分布到 PG——即「状态分布式、协调本地」的不一致。

多副本部署前须将 session execution ownership 上移：Postgres/Redis 分布式 lease，
或交由 admission / durable execution 系统持有（本期不做，属演进方向）。

借鉴 OpenCode V2 SessionRunCoordinator：
- joins same-Session resumes（同 session 互斥）
- 允许不同 Sessions 并发（异 session 不阻塞）

P4-3（coalesce 诚实改名）：原三策略 coalesce/queue/reject 中 coalesce 已退化为
queue（代码注释自认），名称 ≠ 语义属架构债。现将 coalesce 从策略枚举中移除，
仅保留 queue/reject 二策略；若后续需真 coalesce（取消旧请求），按独立专项实施。
"""

import asyncio
import logging
from collections import deque
from typing import Literal

from agent_runtime.schemas import CoordinationDecision

logger = logging.getLogger(__name__)


class SessionCoordinator:
    """Per-session 互斥 + queue/reject 二策略。

    queue 策略下，acquire 返回 decision_type="queue" 后调用方需 await wait_for_turn()
    等待获取执行权；release() 唤醒队列下一个请求。
    """

    def __init__(
        self,
        policy: Literal["queue", "reject"] = "queue",
        enabled: bool = True,
    ) -> None:
        self._policy = policy
        self._enabled = enabled
        self._active: dict[str, str] = {}  # session_id -> request_id（当前执行中）
        self._queues: dict[str, asyncio.Queue] = {}
        self._conditions: dict[str, asyncio.Condition] = {}
        self._cancelled: set[str] = set()  # 已取消（客户端断开 / 超时）的请求
        self._logger = logging.getLogger(__name__)

    async def acquire(
        self, session_id: str, request_id: str
    ) -> CoordinationDecision:
        """获取会话执行权。返回协调决策。

        queue 策略下会话忙碌时返回 decision_type="queue"，
        调用方发送排队事件后需 await wait_for_turn() 等待执行权。
        """
        if not self._enabled:
            return CoordinationDecision(
                decision_type="serialize", request_id=request_id
            )

        try:
            cond = self._conditions.setdefault(session_id, asyncio.Condition())
            async with cond:
                active = self._active.get(session_id)

                if active is None:
                    # 会话空闲，直接获取
                    self._active[session_id] = request_id
                    self._logger.info(
                        "coordination serialize session=%s request=%s",
                        session_id,
                        request_id,
                    )
                    return CoordinationDecision(
                        decision_type="serialize", request_id=request_id
                    )

                # 会话忙碌，按策略处理（仍在锁内，使入队与 release 串行化，
                # 避免「release 清空 active 时 B 尚未入队 → B 入队后无人唤醒」的丢失唤醒竞态）
                if self._policy == "reject":
                    self._logger.info(
                        "coordination reject session=%s request=%s",
                        session_id,
                        request_id,
                    )
                    return CoordinationDecision(
                        decision_type="reject", request_id=request_id
                    )

                else:  # queue
                    q = self._queues.setdefault(session_id, asyncio.Queue())
                    await q.put(request_id)
                    self._logger.info(
                        "coordination queue session=%s request=%s",
                        session_id,
                        request_id,
                    )
                    return CoordinationDecision(
                        decision_type="queue",
                        request_id=request_id,
                        wait_seconds=float(q.qsize()),
                    )

        except Exception:
            # 协调器内部错误：降级为无互斥并发执行
            self._logger.warning(
                "COORDINATION_DEGRADED session=%s request=%s",
                session_id,
                request_id,
                exc_info=True,
            )
            return CoordinationDecision(
                decision_type="serialize", request_id=request_id
            )

    async def cancel(self, session_id: str, request_id: str) -> None:
        """取消一个请求（客户端断开 / 超时）。幂等。

        将 request_id 从会话队列中移除（若仍在排队、尚未 active），并加入
        _cancelled。否则排队中已死但未 active 的请求会被 release() 误 promote 成
        active，导致会话永久卡死（审计 #四：coordinator queue cancellation）。

        对已经 active 的请求调用 cancel 无效——active 请求走 release() 释放。
        """
        if not self._enabled:
            return
        self._cancelled.add(request_id)
        q = self._queues.get(session_id)
        if q is not None and not q.empty():
            # asyncio.Queue 无 remove，重建过滤掉被取消的请求。
            # 必须保持 _queue 为 collections.deque：若替换成 list，
            # 后续 get_nowait()→_get()→popleft() 会抛 AttributeError
            # （list 无 popleft），异常被 release() 吞掉后会话清理中断。
            remaining = deque(r for r in q._queue if r != request_id)
            if len(remaining) != q.qsize():
                q._queue = remaining
                # 同步修正 unfinished 计数（被取消请求从未被消费），避免 join() 挂起
                q._unfinished_tasks = len(remaining)
        cond = self._conditions.setdefault(session_id, asyncio.Condition())
        async with cond:
            cond.notify_all()

    async def wait_for_turn(self, session_id: str, request_id: str) -> bool:
        """排队请求等待获取执行权。

        acquire() 返回 decision_type="queue" 后调用此方法，
        阻塞直到 release() 将本请求设为 active。
        返回 True 表示获得执行权；False 表示自身已被 cancel（被取消）。
        """
        if not self._enabled:
            return True
        cond = self._conditions.setdefault(session_id, asyncio.Condition())
        async with cond:
            while self._active.get(session_id) != request_id:
                if request_id in self._cancelled:
                    # 自身已被取消：不占用执行权，立即退出避免永久挂起
                    return False
                await cond.wait()
            self._cancelled.discard(request_id)
            return True

    async def release(self, session_id: str, request_id: str) -> None:
        """释放会话执行权，唤醒队列下一个。"""
        if not self._enabled:
            return

        try:
            cond = self._conditions.setdefault(session_id, asyncio.Condition())
            async with cond:
                if self._active.get(session_id) == request_id:
                    del self._active[session_id]
                # 唤醒队列下一个（跳过已取消的请求，避免 promote 死请求导致会话卡死）
                q = self._queues.get(session_id)
                _next = None
                while q is not None and not q.empty():
                    cand = q.get_nowait()
                    if cand not in self._cancelled:
                        _next = cand
                        break
                if _next is not None:
                    self._active[session_id] = _next
                    cond.notify_all()
                else:
                    # 本会话已无活动请求且无存活等待者：清理字典条目，避免只增不清
                    if self._active.get(session_id) == request_id:
                        self._active.pop(session_id, None)
                    # acquire 对每个 session 都无条件建了 _conditions[session_id]，
                    # 故清理不看 q 是否为 None：队列不存在或已空都需清，否则单请求
                    # session 的 _conditions 残留（无队列路径 q is None 原被跳过）。
                    if q is None or q.empty():
                        self._queues.pop(session_id, None)
                        self._conditions.pop(session_id, None)
        except Exception:
            self._logger.warning(
                "coordination release failed session=%s request=%s",
                session_id,
                request_id,
                exc_info=True,
            )
