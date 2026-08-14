"""durable admission：持久化准入控制。

请求入队持久化至 PostgreSQL，进程崩溃后队列元数据可恢复。
admission 默认 false（opt-in），DATABASE_URL 为空时自动禁用。
队列不存储 question 全文（脱敏约束）。
"""

import logging

from agent_core.guardrails.ratelimit import SlidingWindowRateLimiter
from app.schemas import AdmissionDecision, Priority

logger = logging.getLogger(__name__)


class RateLimiter:
    """三维滑动窗口限流（per-user / per-session / global）。

    复用 agent_core.guardrails.ratelimit.SlidingWindowRateLimiter，
    持有三个独立实例分别对应 user / session / global 维度（1 秒窗口）。
    """

    def __init__(self, per_user: int, per_session: int, global_: int) -> None:
        self._user_limiter = SlidingWindowRateLimiter(per_user, window_seconds=1)
        self._session_limiter = SlidingWindowRateLimiter(per_session, window_seconds=1)
        self._global_limiter = SlidingWindowRateLimiter(global_, window_seconds=1)

    def check(self, user_id: str, session_id: str) -> bool:
        for limiter, key in (
            (self._user_limiter, user_id),
            (self._session_limiter, session_id),
            (self._global_limiter, "_"),
        ):
            allowed, _ = limiter.allow(key)
            if not allowed:
                return False
        return True


class AdmissionQueue:
    """PG 持久化准入队列 + 优先级调度。"""

    def __init__(
        self,
        pool,
        capacity: int = 100,
        timeout_seconds: float = 10.0,
        rate_limiter: RateLimiter | None = None,
        effective_enabled: bool = False,
    ) -> None:
        self._pool = pool
        self._capacity = capacity
        self._timeout = timeout_seconds
        self._limiter = rate_limiter or RateLimiter(10, 10, 100)
        self._effective_enabled = effective_enabled

    async def enqueue(
        self,
        request_id: str,
        session_id: str,
        user_id: str,
        priority: Priority = "normal",
    ) -> AdmissionDecision:
        """请求入队。未启用时直接 admitted。"""
        if not self._effective_enabled:
            return AdmissionDecision(status="admitted", priority=priority)

        # 限流检查
        if not self._limiter.check(user_id, session_id):
            return AdmissionDecision(
                status="rejected", priority=priority, reason="RATE_LIMITED"
            )

        try:
            async with self._pool.connection() as conn:
                # 容量检查
                row = await conn.execute(
                    "SELECT count(*) FROM admission_queue WHERE status = 'queued'"
                )
                count = await row.fetchone() if hasattr(row, "fetchone") else row
                current = count[0] if count else 0

                if current >= self._capacity:
                    # 按优先级拒绝最低优先级请求
                    await conn.execute(
                        "UPDATE admission_queue SET status = 'rejected', "
                        "rejection_reason = 'ADMISSION_QUEUE_FULL' "
                        "WHERE request_id = ("
                        "  SELECT request_id FROM admission_queue "
                        "  WHERE status = 'queued' "
                        "  ORDER BY priority ASC, created_at DESC LIMIT 1)"
                    )
                    return AdmissionDecision(
                        status="rejected",
                        priority=priority,
                        reason="ADMISSION_QUEUE_FULL",
                    )

                # 持久化（不含 question 全文）
                await conn.execute(
                    "INSERT INTO admission_queue "
                    "(request_id, session_id, user_id, priority, status, created_at, queue_position) "
                    "VALUES (%s, %s, %s, %s, 'queued', now(), %s)",
                    (request_id, session_id, user_id, priority, current + 1),
                )

                return AdmissionDecision(
                    status="queued",
                    queue_position=current + 1,
                    priority=priority,
                    estimated_wait_seconds=self._timeout,
                )
        except Exception:
            logger.warning("admission enqueue failed", exc_info=True)
            return AdmissionDecision(
                status="rejected", priority=priority, reason="ADMISSION_UNAVAILABLE"
            )

    async def admit_next(self) -> str | None:
        """按优先级 + FIFO 取出下一个请求。"""
        if not self._effective_enabled or self._pool is None:
            return None
        try:
            async with self._pool.connection() as conn:
                row = await conn.execute(
                    "UPDATE admission_queue SET status = 'admitted', admitted_at = now() "
                    "WHERE request_id = ("
                    "  SELECT request_id FROM admission_queue "
                    "  WHERE status = 'queued' "
                    "  ORDER BY priority DESC, created_at ASC LIMIT 1) "
                    "RETURNING request_id"
                )
                result = await row.fetchone() if hasattr(row, "fetchone") else row
                return result[0] if result else None
        except Exception:
            logger.warning("admission admit_next failed", exc_info=True)
            return None

    async def recover_on_startup(self) -> int:
        """崩溃恢复：已入队未执行请求标记 rejected。"""
        if self._pool is None:
            return 0
        try:
            async with self._pool.connection() as conn:
                result = await conn.execute(
                    "UPDATE admission_queue SET status = 'rejected', "
                    "rejection_reason = 'PROCESS_RESTART' "
                    "WHERE status IN ('queued', 'executing')"
                )
                return result.rowcount if hasattr(result, "rowcount") else 0
        except Exception:
            logger.warning("admission recover failed", exc_info=True)
            return 0

    async def mark_completed(self, request_id: str) -> None:
        """标记请求完成。"""
        if self._pool is None:
            return
        try:
            async with self._pool.connection() as conn:
                await conn.execute(
                    "UPDATE admission_queue SET status = 'completed', completed_at = now() "
                    "WHERE request_id = %s",
                    (request_id,),
                )
        except Exception:
            logger.warning("admission mark_completed failed", exc_info=True)
