# -*- coding: utf-8 -*-
"""幂等异步租约（Lease）：结构化生命周期清理原语。

背景（agent-platform v2 平台内核收敛，承接代码审计 P0 #一/#二、P1 #四）：
  ``/query`` 的 coordinator 槽位、admission capacity 等「获取后必须释放」的资源，
  此前靠手写 try/finally + bool 守卫的 ``_cleanup`` 闭包收敛。该模式每个调用方
  都要自己保证「任何 acquire 都对应 release/cancel」，容易散落与遗漏。

Lease 把释放动作注册进一个对象，由 ``release()`` 统一、幂等、异常隔离地执行：

    lease = AsyncLease()
    lease.on_release(lambda: coordinator.release(session_id, request_id))
    lease.on_release(lambda: admission_queue.mark_completed(request_id))
    ...
    await lease.release()          # 幂等；可多次调用 / 在 finally 中调用

约束：Lease 是协议，不是具体状态机——Admission / Coordinator / CircuitBreaker
各自内部状态机保持不变，只统一「获取 / 释放」生命周期（Level 3：概念相同→抽
Protocol，不硬塞父类；AdmissionLease / CoordinatorLease 只是不同 release 回调
组合，无需各自成类）。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

ReleaseCallback = Callable[[], Awaitable[Any]]


class AsyncLease:
    """幂等异步租约。

    - ``on_release(cb)``：注册释放回调（无参 async 可调用，可用闭包/偏函数绑定
      实参），返回 self 支持链式注册。
    - ``release()``：按注册顺序执行全部回调，仅执行一次（幂等）；单个回调异常
      不影响其余回调执行（异常隔离），异常统一记录日志、不向调用方重抛——
      清理阶段的失败不应吞掉主流程结果。
    - 支持 ``async with``：块正常/异常退出时自动 ``release()``。
    """

    def __init__(self) -> None:
        self._callbacks: list[ReleaseCallback] = []
        self._released = False

    def on_release(self, callback: ReleaseCallback) -> "AsyncLease":
        """注册一个释放回调（可重复调用注册多个资源）。"""
        self._callbacks.append(callback)
        return self

    async def release(self) -> None:
        """按注册顺序执行全部释放回调（幂等：多次调用只执行一次）。"""
        if self._released:
            return
        self._released = True
        callbacks, self._callbacks = self._callbacks, []
        for callback in callbacks:
            try:
                await callback()
            except Exception:
                logger.exception("AsyncLease release 回调执行失败: %r", callback)

    async def __aenter__(self) -> "AsyncLease":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.release()


__all__ = ["AsyncLease", "ReleaseCallback"]
