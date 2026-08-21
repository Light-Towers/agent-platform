"""Admission 统一入口（§9.2 / Phase E）+ Idempotency 测试。"""

from __future__ import annotations

import pytest
from agent_runtime.admission_gateway import (
    AdmissionRejected,
    InMemoryAdmissionController,
    run_admitted,
)
from agent_runtime.planner.durability import (
    IdempotencyStore,
    InMemoryIdempotencyStore,
    with_idempotency,
)


class _StubPlanner:
    def __init__(self):
        self.plans = 0
        self.executes = 0
        self.last_query = None

    async def plan(self, query, runtime, **kw):
        self.plans += 1
        self.last_query = query
        return {"query": query}

    async def execute(self, plan, runtime, **kw):
        self.executes += 1
        return {"answer": plan["query"]}


async def test_run_admitted_skips_when_no_controller():
    p = _StubPlanner()
    out = await run_admitted(None, p, None, "hi", session_id="s", user_id="u")
    assert out == {"answer": "hi"}
    assert p.plans == 1 and p.executes == 1


async def test_run_admitted_capacity_admitted():
    ctrl = InMemoryAdmissionController(capacity=2)
    p = _StubPlanner()
    out = await run_admitted(ctrl, p, None, "q", session_id="s", user_id="u")
    assert out == {"answer": "q"}


async def test_run_admitted_releases_capacity_on_completion():
    ctrl = InMemoryAdmissionController(capacity=1)
    p = _StubPlanner()
    # 第一次占用容量，完成后释放
    await run_admitted(ctrl, p, None, "q1", session_id="s", user_id="u")
    assert ctrl._active == 0  # 已释放
    await run_admitted(ctrl, p, None, "q2", session_id="s", user_id="u")
    assert p.executes == 2


async def test_run_admitted_rejects_when_overloaded_then_recovered():
    ctrl = InMemoryAdmissionController(capacity=1, timeout_s=0.02)
    # 先占满容量（模拟有在途请求），新请求将排队并在超时后被拒
    ctrl._active = 1

    with pytest.raises(AdmissionRejected):
        await run_admitted(ctrl, _StubPlanner(), None, "q", session_id="s", user_id="u")


async def test_idempotency_caches_second_call():
    store: IdempotencyStore = InMemoryIdempotencyStore()
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        return {"result": calls["n"]}

    out1 = await with_idempotency("k1", store, fn)
    out2 = await with_idempotency("k1", store, fn)
    assert out1 == out2 == {"result": 1}
    assert calls["n"] == 1  # 第二次命中缓存，未重跑


async def test_idempotency_does_not_cache_on_error():
    store: IdempotencyStore = InMemoryIdempotencyStore()
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return {"ok": True}

    with pytest.raises(RuntimeError):
        await with_idempotency("k2", store, fn)
    out = await with_idempotency("k2", store, fn)
    assert out == {"ok": True}
    assert calls["n"] == 2
