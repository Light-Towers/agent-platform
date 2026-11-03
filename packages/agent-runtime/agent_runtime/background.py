"""统一的后台任务派发：持有引用防 GC，并提供在途计数。

原实现寄居在 ``agent_runtime.cache``（PG 语义缓存）里，缓存模块退役后独立为
通用工具，供 MCP / revert 等非缓存调用方继续使用。
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

_background_tasks: set[asyncio.Task] = set()


def spawn_background(coro: Coroutine[Any, Any, Any]) -> asyncio.Task:
    """派发后台任务并持有引用，避免 ``create_task`` 返回值被 GC 提前回收。"""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def pending_background_tasks() -> int:
    """返回当前在途后台任务数。"""
    return len(_background_tasks)


__all__ = ["pending_background_tasks", "spawn_background"]
