"""durable admission：持久化准入控制。

请求入队持久化至 PostgreSQL，进程崩溃后队列元数据可恢复。
admission 默认 false（opt-in），DATABASE_URL 为空时自动禁用。
队列不存储 question 全文（脱敏约束）。

方案 A（真正生效的限流闭环）：
- enqueue 在事务内原子判断「进行中(admitted) + 排队(queued)」是否已达 capacity；
  未达 → 直接 admitted 并立即放行；已达 → queued 并阻塞等待。
- wait_for_admit 用 asyncio.Condition 阻塞请求，直到被调度为 admitted（补位）或被拒。
- mark_completed 在请求完成后尝试把最早 queued 提升为 admitted（补位唤醒下一个）。
- recover_on_startup 把崩溃遗留的 queued 标 rejected，并唤醒所有等待者。
"""

import asyncio
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
    """PG 持久化准入队列 + 优先级调度（真正生效的限流闭环）。"""

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
        # 内存调度状态：request_id -> 当前状态（admitted / queued / rejected）
        self._states: dict[str, str] = {}
        self._cond = asyncio.Condition()

    async def enqueue(
        self,
        request_id: str,
        session_id: str,
        user_id: str,
        priority: Priority = "normal",
    ) -> AdmissionDecision:
        """请求入队/准入。未启用时直接 admitted。"""
        if not self._effective_enabled:
            return AdmissionDecision(status="admitted", priority=priority)

        # 限流检查
        if not self._limiter.check(user_id, session_id):
            return AdmissionDecision(
                status="rejected", priority=priority, reason="RATE_LIMITED"
            )

        try:
            async with self._pool.connection() as conn, conn.transaction():
                # 事务内原子：容量判断 + 写入，避免并发双双通过容量检查导致超容
                row = await conn.execute(
                    "SELECT count(*) FROM admission_queue "
                    "WHERE status IN ('admitted', 'queued')"
                )
                count = await row.fetchone()
                current = count[0] if count else 0

                if current >= self._capacity:
                    # 满队列：当前请求进入排队（queued），等待 mark_completed 补位唤醒
                    await conn.execute(
                        "INSERT INTO admission_queue "
                        "(request_id, session_id, user_id, priority, status, "
                        " created_at, queue_position) "
                        "VALUES (%s, %s, %s, %s, 'queued', now(), %s)",
                        (request_id, session_id, user_id, priority, current + 1),
                    )
                    async with self._cond:
                        self._states[request_id] = "queued"
                        self._cond.notify_all()
                    return AdmissionDecision(
                        status="queued",
                        priority=priority,
                        queue_position=current + 1,
                        estimated_wait_seconds=self._timeout,
                    )

                # 有空位 → 直接 admitted（立即放行，不排队）
                await conn.execute(
                    "INSERT INTO admission_queue "
                    "(request_id, session_id, user_id, priority, status, "
                    " created_at, admitted_at, queue_position) "
                    "VALUES (%s, %s, %s, %s, 'admitted', now(), now(), %s)",
                    (request_id, session_id, user_id, priority, current + 1),
                )
                async with self._cond:
                    self._states[request_id] = "admitted"
                    self._cond.notify_all()
                return AdmissionDecision(
                    status="admitted",
                    priority=priority,
                    queue_position=current + 1,
                )
        except Exception:
            logger.warning("admission enqueue failed", exc_info=True)
            return AdmissionDecision(
                status="rejected", priority=priority, reason="ADMISSION_UNAVAILABLE"
            )

    async def wait_for_admit(self, request_id: str) -> AdmissionDecision:
        """阻塞等待 admission 调度（路径一：排队补位语义）。

        enqueue 返回 queued 时调用：直到该请求被 mark_completed 补位提升为 admitted，
        或因超时/被拒而退出。超时使用单调时钟累计，避免非超时唤醒被误判为超时。
        """
        loop = asyncio.get_event_loop()
        deadline = loop.time() + self._timeout

        async def _mark_db_rejected(reason: str) -> None:
            """超时/取消：把 DB 中仍 queued 的行标为 rejected，使状态机语义干净
            （审计 P1 #三：超时不应伪装成 completed，且立即释放容量）。
            """
            if self._pool is None:
                return
            try:
                async with self._pool.connection() as conn:
                    await conn.execute(
                        "UPDATE admission_queue SET status = 'rejected', "
                        "rejection_reason = %s WHERE request_id = %s AND status = 'queued'",
                        (reason, request_id),
                    )
            except Exception:
                logger.warning("admission timeout db-mark failed", exc_info=True)

        try:
            async with self._cond:
                while self._states.get(request_id) == "queued":
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        self._states[request_id] = "rejected"
                        await _mark_db_rejected("ADMISSION_TIMEOUT")
                        return AdmissionDecision(
                            status="rejected",
                            priority="normal",
                            reason="ADMISSION_TIMEOUT",
                        )
                    try:
                        await asyncio.wait_for(self._cond.wait(), timeout=remaining)
                    except TimeoutError:
                        # 等待期间无其他等待者 notify，确实超时
                        self._states[request_id] = "rejected"
                        await _mark_db_rejected("ADMISSION_TIMEOUT")
                        return AdmissionDecision(
                            status="rejected",
                            priority="normal",
                            reason="ADMISSION_TIMEOUT",
                        )
                state = self._states.get(request_id)
        except Exception:
            logger.warning("admission wait_for_admit failed", exc_info=True)
            return AdmissionDecision(
                status="rejected", priority="normal", reason="ADMISSION_UNAVAILABLE"
            )
        if state == "admitted":
            return AdmissionDecision(status="admitted", priority="normal")
        return AdmissionDecision(
            status="rejected", priority="normal", reason="ADMISSION_REJECTED"
        )

    async def recover_on_startup(self) -> int:
        """崩溃恢复：已入队未执行请求标记 rejected，并唤醒所有等待者。"""
        recovered = 0
        if self._pool is not None:
            try:
                async with self._pool.connection() as conn:
                    result = await conn.execute(
                        "UPDATE admission_queue SET status = 'rejected', "
                        "rejection_reason = 'PROCESS_RESTART' "
                        "WHERE status = 'queued'"
                    )
                    recovered = result.rowcount if hasattr(result, "rowcount") else 0
            except Exception:
                logger.warning("admission recover failed", exc_info=True)
        # 唤醒可能遗留的等待协程，避免挂起
        async with self._cond:
            for rid in list(self._states):
                if self._states[rid] == "queued":
                    self._states[rid] = "rejected"
            self._cond.notify_all()
        return recovered

    async def mark_completed(self, request_id: str) -> None:
        """标记请求完成，并补位提升队首 queued 为 admitted（路径一排队补位）。"""
        if self._pool is None:
            return
        promoted: list[str] = []
        try:
            async with self._pool.connection() as conn, conn.transaction():
                await conn.execute(
                    "UPDATE admission_queue SET status = 'completed', completed_at = now() "
                    "WHERE request_id = %s AND status IN ('admitted', 'queued')",
                    (request_id,),
                )
                # 取队首 queued（按优先级升序、最旧优先），行锁跳过并发已锁行
                row = await conn.execute(
                    "SELECT request_id FROM admission_queue "
                    "WHERE status = 'queued' "
                    "ORDER BY ("
                    "  CASE priority WHEN 'low' THEN 0 "
                    "       WHEN 'normal' THEN 1 "
                    "       WHEN 'high' THEN 2 ELSE 1 END"
                    ") ASC, created_at ASC "
                    "LIMIT 1 FOR UPDATE SKIP LOCKED"
                )
                nxt = await row.fetchone()
                if nxt:
                    nxt_id = nxt[0]
                    await conn.execute(
                        "UPDATE admission_queue SET status = 'admitted', "
                        "admitted_at = now() WHERE request_id = %s",
                        (nxt_id,),
                    )
                    promoted.append(nxt_id)
        except Exception:
            logger.warning("admission mark_completed failed", exc_info=True)
        finally:
            async with self._cond:
                self._states.pop(request_id, None)
                for rid in promoted:
                    self._states[rid] = "admitted"
                self._cond.notify_all()
