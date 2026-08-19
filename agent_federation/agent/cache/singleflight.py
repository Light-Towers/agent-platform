"""Singleflight：同 query 并发只算一次，其余等结果。

用 asyncio.Lock per query_hash 实现。query 结束后 lock 清理。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)

_locks: dict[str, asyncio.Lock] = {}
_inflight_results: dict[str, Any] = {}
_PENDING = object()


async def singleflight(
    key: str,
    fn: Callable[..., Awaitable[Any]],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """对同一 key 的并发调用只执行一次 fn，其余等结果。

    Args:
        key: 去重键（通常是 cache key hash）
        fn: 异步函数
        *args, **kwargs: fn 的参数

    Returns:
        fn 的返回值（所有并发调用者拿到同一结果）
    """
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock

    async with lock:
        result = _inflight_results.get(key, _PENDING)
        if result is not _PENDING:
            logger.debug("singleflight 命中: %s", key)
            return result

        try:
            result = await fn(*args, **kwargs)
            _inflight_results[key] = result
            return result
        finally:
            _locks.pop(key, None)
            loop = asyncio.get_event_loop()
            loop.call_later(300, lambda: _inflight_results.pop(key, None))
