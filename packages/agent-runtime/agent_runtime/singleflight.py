"""Singleflight：同 key 并发只算一次，其余等结果。

用 asyncio.Lock per key 实现，带引用计数（P2-2 结构性修复）。
解决原始「call_later 无条件 pop 可在异常路径 + fn>300s 时删掉正在使用的锁」的竞态。

核心保证：只有当 _refs[key]==0（无人持有/等待该 lock）时才执行清理。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)

_locks: dict[str, asyncio.Lock] = {}
_refs: dict[str, int] = {}
_inflight_results: dict[str, Any] = {}
_PENDING = object()


def _cleanup(key: str, lock: asyncio.Lock) -> None:
    """Scheduled cleanup: only pop when refcount is zero AND lock identity matches."""
    if _refs.get(key, 0) > 0:
        return  # 还有人持有/等待，不删
    if _locks.get(key) is not lock:
        return  # 已被替换，不删
    _locks.pop(key, None)
    _inflight_results.pop(key, None)
    _refs.pop(key, None)


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

    _refs[key] = _refs.get(key, 0) + 1
    try:
        async with lock:
            result = _inflight_results.get(key, _PENDING)
            if result is not _PENDING:
                logger.debug("singleflight 命中: %s", key)
                return result

            result = await fn(*args, **kwargs)
            _inflight_results[key] = result
            return result
    finally:
        _refs[key] -= 1
        if _refs[key] == 0:
            loop = asyncio.get_running_loop()
            loop.call_later(300, _cleanup, key, lock)


__all__ = ["singleflight"]
