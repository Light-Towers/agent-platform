"""Middleware（§9.2 retry/rate/audit）测试。"""

from __future__ import annotations

import pytest
from agent_runtime.skills.middleware import (
    AuditMiddleware,
    RateLimitMiddleware,
    RetryMiddleware,
    SimpleTokenBucket,
)
from agent_runtime.skills.registry import SkillExecutionError


async def _ok(name, kwargs):
    return {"ok": kwargs}


class _TransientError(Exception):
    """类名含 Transient，命中 RetryMiddleware 默认瞬态判定。"""


async def _boom(name, kwargs):
    raise _TransientError("transient failure")


async def test_retry_transient_then_success():
    calls = {"n": 0}

    async def _flaky(name, kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _TransientError("boom")
        return {"ok": True}

    mw = RetryMiddleware(max_retries=3, backoff_s=0)

    async def call_next(name, kwargs):
        return await _flaky(name, kwargs)

    out = await mw.around("s", {}, call_next)
    assert out == {"ok": True}
    assert calls["n"] == 3


async def test_retry_gives_up_on_permanent():
    mw = RetryMiddleware(max_retries=2, backoff_s=0)

    async def call_next(name, kwargs):
        return await _boom(name, kwargs)

    with pytest.raises(_TransientError):
        await mw.around("s", {}, call_next)
    # 1 初次 + 2 重试 = 3 次
    n = {"c": 0}

    async def _counting(name, kwargs):
        n["c"] += 1
        raise _TransientError("boom")

    async def cn(name, kwargs):
        return await _counting(name, kwargs)

    with pytest.raises(_TransientError):
        await RetryMiddleware(max_retries=2, backoff_s=0).around("s", {}, cn)
    assert n["c"] == 3


async def test_retry_skip_unrelated_skill():
    mw = RetryMiddleware(max_retries=5, skill_names=("other",))
    n = {"c": 0}

    async def cn(name, kwargs):
        n["c"] += 1
        raise _TransientError("boom")

    with pytest.raises(_TransientError):
        await mw.around("s", {}, cn)
    assert n["c"] == 1  # 不在作用域，不重试


async def test_rate_limit_blocks_after_capacity():
    bucket = SimpleTokenBucket(rate=0.0, capacity=2)
    mw = RateLimitMiddleware(bucket, skill_names=("s",))

    async def call_next(name, kwargs):
        return {"ok": True}

    assert await mw.around("s", {}, call_next) == {"ok": True}
    assert await mw.around("s", {}, call_next) == {"ok": True}
    with pytest.raises(SkillExecutionError):
        await mw.around("s", {}, call_next)


async def test_rate_limit_skip_unrelated_skill():
    bucket = SimpleTokenBucket(rate=0.0, capacity=0)
    mw = RateLimitMiddleware(bucket, skill_names=("other",))

    async def call_next(name, kwargs):
        return {"ok": True}

    assert await mw.around("s", {}, call_next) == {"ok": True}


async def test_audit_records_success_and_failure():
    events: list = []

    async def sink(name, kwargs, result, error, latency):
        events.append((name, result, error))

    mw = AuditMiddleware(sink)

    async def call_next(name, kwargs):
        return await _ok(name, kwargs)

    await mw.around("s", {"q": 1}, call_next)
    assert events[-1][0] == "s" and events[-1][1] == {"ok": {"q": 1}} and events[-1][2] is None

    async def call_next_boom(name, kwargs):
        return await _boom(name, kwargs)

    with pytest.raises(_TransientError):
        await mw.around("s", {}, call_next_boom)
    assert events[-1][2] is not None  # 失败也落审计


async def test_middleware_applies_via_registry_execute():
    """新中间件经 registry.execute 洋葱链真实生效（非死代码）。"""
    from agent_runtime.skills.registry import Skill, SkillKind, SkillRegistry

    calls = {"n": 0}

    async def _flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            raise _TransientError("boom")
        return {"ok": True}

    reg = SkillRegistry(middlewares=[RetryMiddleware(max_retries=3, backoff_s=0)])
    reg.register(Skill("s", "flaky", SkillKind.FUNCTION, _flaky))

    out = await reg.execute("s")
    assert out == {"ok": True}
    assert calls["n"] == 2  # 第一次失败被重试中间件重试成功

