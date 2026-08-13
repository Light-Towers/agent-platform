"""会话并发协调器：同 session 串行 / 异 session 并发。

借鉴 OpenCode V2 SessionRunCoordinator：
- joins same-Session resumes（同 session 互斥）
- coalesces prompt wakeups（合并策略）
- 允许不同 Sessions 并发（异 session 不阻塞）
"""

import asyncio
import logging
from typing import Literal

from app.schemas import CoordinationDecision

logger = logging.getLogger(__name__)


class SessionCoordinator:
    """Per-session 互斥 + coalesce/queue/reject 三策略。

    queue 策略下，acquire 返回 decision_type="queue" 后调用方需 await wait_for_turn()
    等待获取执行权；release() 唤醒队列下一个请求。
    """

    def __init__(
        self,
        policy: Literal["coalesce", "queue", "reject"] = "queue",
        enabled: bool = True,
    ) -> None:
        self._policy = policy
        self._enabled = enabled
        self._active: dict[str, str] = {}  # session_id -> request_id（当前执行中）
        self._queues: dict[str, asyncio.Queue] = {}
        self._conditions: dict[str, asyncio.Condition] = {}
        self._logger = logging.getLogger(__name__)

    async def acquire(
        self, session_id: str, request_id: str
    ) -> CoordinationDecision:
        """获取会话执行权。返回协调决策。

        queue/coalesce 策略下会话忙碌时返回 decision_type="queue"，
        调用方发送排队事件后需 await wait_for_turn() 等待执行权。
        """
        if not self._enabled:
            return CoordinationDecision(
                decision_type="serialize", request_id=request_id
            )

        try:
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

            # 会话忙碌，按策略处理
            if self._policy == "coalesce":
                # 旧请求尚未进入能力节点（仅在排队）→ 取消旧请求
                # 简化实现：旧请求已 active 则不取消（COALESCE_SKIPPED），新请求排队
                self._logger.info(
                    "coordination COALESCE_SKIPPED session=%s old=%s new=%s",
                    session_id,
                    active,
                    request_id,
                )
                q = self._queues.setdefault(session_id, asyncio.Queue())
                await q.put(request_id)
                return CoordinationDecision(
                    decision_type="queue",
                    request_id=request_id,
                    wait_seconds=0.0,
                )

            elif self._policy == "reject":
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
                    wait_seconds=0.0,
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

    async def wait_for_turn(self, session_id: str, request_id: str) -> None:
        """排队请求等待获取执行权。

        acquire() 返回 decision_type="queue" 后调用此方法，
        阻塞直到 release() 将本请求设为 active。
        """
        if not self._enabled:
            return
        cond = self._conditions.setdefault(session_id, asyncio.Condition())
        async with cond:
            while self._active.get(session_id) != request_id:
                await cond.wait()

    async def release(self, session_id: str, request_id: str) -> None:
        """释放会话执行权，唤醒队列下一个。"""
        if not self._enabled:
            return

        try:
            cond = self._conditions.get(session_id)
            if self._active.get(session_id) == request_id:
                del self._active[session_id]
            # 唤醒队列下一个（如有）
            q = self._queues.get(session_id)
            if q is not None and not q.empty():
                _next = q.get_nowait()
                self._active[session_id] = _next
                if cond is not None:
                    async with cond:
                        cond.notify_all()
        except Exception:
            self._logger.warning(
                "coordination release failed session=%s request=%s",
                session_id,
                request_id,
                exc_info=True,
            )
