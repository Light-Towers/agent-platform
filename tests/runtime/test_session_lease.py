"""P4-1 分布式 session lease 后端测试。

- InMemoryLeaseBackend：进程内单飞语义
- PgAdvisoryLeaseBackend：用 FakePgPool 验证 SQL 单飞 + 双写本地镜像 + TTL 过期 + 释放
（无真实 PG，Fake 实现 asyncpg 风格的 acquire/fetchval/execute 接口）
"""

import asyncio
import time

import pytest
from agent_runtime.coordinator import (
    InMemoryLeaseBackend,
    PgAdvisoryLeaseBackend,
    SessionCoordinator,
)


class _FakeConn:
    def __init__(self, store: dict):
        self._store = store  # session_id -> (owner, expires_at_ts)

    async def fetchval(self, sql, session_id, owner, ttl):
        now = time.monotonic()
        cur = self._store.get(session_id)
        if cur is None or cur[1] < now:
            self._store[session_id] = (owner, now + float(ttl))
            return owner
        return cur[0]

    async def execute(self, sql, session_id, owner):
        cur = self._store.get(session_id)
        if cur is not None and cur[0] == owner:
            self._store.pop(session_id, None)


class _FakePool:
    def __init__(self):
        self._store: dict = {}

    def acquire(self):
        return _Ctx(self)


class _Ctx:
    def __init__(self, pool: _FakePool):
        self._pool = pool

    async def __aenter__(self):
        return _FakeConn(self._pool._store)

    async def __aexit__(self, *exc):
        return False


# ---- InMemoryLeaseBackend ----

@pytest.mark.asyncio
async def test_inmemory_single_flight():
    b = InMemoryLeaseBackend()
    assert await b.try_acquire("s1", "r1", 300) is True
    assert await b.try_acquire("s1", "r2", 300) is False  # 同 session 仅一 owner
    assert await b.try_acquire("s2", "r9", 300) is True
    await b.release("s1", "r1")
    assert await b.try_acquire("s1", "r3", 300) is True
    await b.release("s1", "r3")  # 非 owner 释放 no-op
    await b.release("s2", "r9")


@pytest.mark.asyncio
async def test_inmemory_release_wrong_owner_noop():
    b = InMemoryLeaseBackend()
    await b.try_acquire("s", "r1", 300)
    await b.release("s", "rX")  # 非持有者
    assert await b.try_acquire("s", "r2", 300) is False  # 仍被 r1 持有
    await b.release("s", "r1")


# ---- PgAdvisoryLeaseBackend（Fake 池）----

@pytest.mark.asyncio
async def test_pg_single_flight_and_dual_write():
    pool = _FakePool()
    b = PgAdvisoryLeaseBackend(pool)
    assert await b.try_acquire("s1", "r1", 300) is True
    assert await b.try_acquire("s1", "r2", 300) is False
    # 双写：本地镜像也应记录 owner
    assert await b._local.try_acquire("s1", "probe", 300) is False
    await b.release("s1", "r1")
    assert await b.try_acquire("s1", "r3", 300) is True
    await b.release("s1", "r3")


@pytest.mark.asyncio
async def test_pg_ttl_expiry_allows_reacquire():
    pool = _FakePool()
    b = PgAdvisoryLeaseBackend(pool, ttl=0.05)
    assert await b.try_acquire("s", "r1", 0.05) is True
    assert await b.try_acquire("s", "r2", 0.05) is False
    await asyncio.sleep(0.1)
    # TTL 过期后另一 owner 可取得（expires_at < now）
    assert await b.try_acquire("s", "r2", 0.05) is True
    await b.release("s", "r2")


@pytest.mark.asyncio
async def test_pg_release_wrong_owner_noop():
    pool = _FakePool()
    b = PgAdvisoryLeaseBackend(pool)
    await b.try_acquire("s", "r1", 300)
    await b.release("s", "rX")  # no-op
    assert await b.try_acquire("s", "r2", 300) is False
    await b.release("s", "r1")


# ---- Coordinator 注入后端：serialize 经 lease 单飞 ----

@pytest.mark.asyncio
async def test_coordinator_injects_lease_backend():
    backend = InMemoryLeaseBackend()
    coord = SessionCoordinator(policy="reject", lease_backend=backend)
    d1 = await coord.acquire("s", "r1")
    assert d1.decision_type == "serialize"
    # 第二请求应被 reject（因 lease 已授予 r1）
    d2 = await coord.acquire("s", "r2")
    assert d2.decision_type == "reject"
    await coord.release("s", "r1")
    d3 = await coord.acquire("s", "r3")
    assert d3.decision_type == "serialize"
    await coord.release("s", "r3")


@pytest.mark.asyncio
async def test_coordinator_distributed_backend_rejects_cross_owner():
    pool = _FakePool()
    backend = PgAdvisoryLeaseBackend(pool)
    coord = SessionCoordinator(policy="reject", lease_backend=backend)
    assert (await coord.acquire("s", "r1")).decision_type == "serialize"
    # 模拟「另一进程」并发请求同 session：PG 单飞应拒绝
    assert (await coord.acquire("s", "r2")).decision_type == "reject"
    await coord.release("s", "r1")
    assert (await coord.acquire("s", "r3")).decision_type == "serialize"
    await coord.release("s", "r3")
