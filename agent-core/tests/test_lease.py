# -*- coding: utf-8 -*-
"""AsyncLease 幂等租约单元测试（平台内核生命周期原语）。"""

import asyncio

import pytest

from agent_core.runtime.lease import AsyncLease


async def _noop() -> None:
    return None


def test_on_release_returns_self_for_chaining() -> None:
    lease = AsyncLease()
    assert lease.on_release(_noop) is lease


def test_release_runs_all_callbacks_in_order_and_idempotent() -> None:
    """release() 按注册顺序执行全部回调，且每个只执行一次（幂等）。"""
    order: list[int] = []

    async def cb1() -> None:
        order.append(1)

    async def cb2() -> None:
        order.append(2)

    lease = AsyncLease().on_release(cb1).on_release(cb2)
    asyncio.run(lease.release())
    assert order == [1, 2]
    # 幂等：再次调用不重复执行
    asyncio.run(lease.release())
    assert order == [1, 2]


def test_release_is_idempotent_under_concurrent_awaits() -> None:
    """并发重复 release 只执行一次回调（asyncio.gather 竞争安全）。"""
    calls: list[int] = []

    async def cb() -> None:
        calls.append(1)

    lease = AsyncLease().on_release(cb)

    async def main() -> None:
        await asyncio.gather(lease.release(), lease.release())

    asyncio.run(main())
    assert calls == [1]


def test_release_isolates_callback_exceptions() -> None:
    """单个回调抛异常不影响其余回调执行，且不向调用方重抛。"""
    calls: list[str] = []

    async def boom() -> None:
        raise RuntimeError("cb failed")

    async def ok() -> None:
        calls.append("ok")

    lease = AsyncLease().on_release(boom).on_release(ok)
    asyncio.run(lease.release())  # 不重抛
    assert calls == ["ok"]


def test_async_with_releases_on_normal_exit() -> None:
    """async with 正常退出自动 release。"""
    calls: list[str] = []

    async def cb() -> None:
        calls.append("released")

    async def main() -> None:
        async with AsyncLease().on_release(cb):
            pass

    asyncio.run(main())
    assert calls == ["released"]


def test_async_with_releases_on_exception() -> None:
    """async with 异常退出自动 release（清理不能被异常吞掉）。"""
    calls: list[str] = []

    async def cb() -> None:
        calls.append("released")

    async def main() -> None:
        with pytest.raises(ValueError):
            async with AsyncLease().on_release(cb):
                raise ValueError("boom")

    asyncio.run(main())
    assert calls == ["released"]
