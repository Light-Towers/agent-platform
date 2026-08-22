"""M5：连接池关闭竞态单测（agent_runtime.db.close_pool / init_pool）。

覆盖五类场景（详见 docs/plan-m3-m5-logging-pool.md §1.4）：
- Case A：关闭前已借连接，close 后在途连接仍可用并正常释放。
- Case B：关闭后新请求 get_pool() 返回 None。
- Case C：关闭进行中调用 init_pool() 返回 None，绝不创建第二个池。
- Case D：重复 close 仅真正关闭一次（幂等）。
- Case E：close() 自身异常被记录且 _closing 复位，不永久卡死。

不依赖真实数据库，使用 FakePool 模拟 psycopg AsyncConnectionPool 的
connection()/close(timeout=) 行为。
"""

import asyncio

import agent_runtime.db as db
import pytest


class FakeConnection:
    def __init__(self, pool):
        self.pool = pool
        self.executed = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, sql, *args):
        self.executed.append(sql)
        return None


class _ConnCM:
    def __init__(self, pool):
        self.pool = pool

    async def __aenter__(self):
        self.pool.connections += 1
        return FakeConnection(self.pool)

    async def __aexit__(self, *exc):
        self.pool.connections -= 1
        return False


class FakePool:
    def __init__(self, *args, **kwargs):
        self.close_count = 0
        self.closed = False
        self.raise_on_close = False
        self.connections = 0
        self._block: asyncio.Event | None = None  # 测试用：close 进行中阻塞，制造 _closing 窗口

    def connection(self):
        # 模拟 psycopg AsyncConnectionPool.connection() -> 异步上下文管理器
        return _ConnCM(self)

    async def close(self, timeout=None):
        self.close_count += 1
        if self._block is not None:
            await self._block.wait()  # 测试用：close 进行中阻塞，制造 _closing 窗口
        if self.raise_on_close:
            raise RuntimeError("simulated close failure")
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_pool_state():
    db._pool = None
    db._closing = False
    yield
    db._pool = None
    db._closing = False


async def test_case_a_inflight_connection_survives_close():
    pool = FakePool()
    db._pool = pool
    cm = pool.connection()
    conn = await cm.__aenter__()
    # 关闭进行中：已借出的连接在途仍可使用
    await db.close_pool()
    await conn.execute("SELECT 1")
    assert pool.closed is True
    assert "SELECT 1" in conn.executed
    await cm.__aexit__(None, None, None)
    # 关闭后全局池已摘除
    assert db.get_pool() is None


async def test_case_b_get_pool_none_after_close():
    pool = FakePool()
    db._pool = pool
    await db.close_pool()
    assert db.get_pool() is None
    assert pool.closed is True
    assert pool.close_count == 1


async def test_case_c_init_during_closing_returns_none():
    orig = FakePool()
    db._pool = orig
    db._closing = True  # 模拟关闭进行中
    result = await db.init_pool(database_url="postgresql://dummy")
    assert result is None
    # _closing 未被 init 复位；全局池未被覆盖成第二个池
    assert db._closing is True
    assert db._pool is orig


async def test_case_c_concurrent_close_and_init():
    pool = FakePool()
    pool._block = asyncio.Event()  # close 进行中阻塞，确保 _closing 窗口可见
    db._pool = pool

    async def closer():
        await db.close_pool()

    task = asyncio.create_task(closer())
    # 等待 close 进入 _closing 状态（在 await pool.close 之前已置位）
    for _ in range(200):
        if db._closing:
            break
        await asyncio.sleep(0.001)
    assert db._closing is True
    # 关闭进行中调用 init：应返回 None，绝不创建第二个池
    result = await db.init_pool(database_url="postgresql://dummy")
    assert result is None
    pool._block.set()  # 放行 close
    await task
    assert db._pool is None


async def test_case_d_repeated_close_idempotent():
    pool = FakePool()
    db._pool = pool
    for _ in range(5):
        await db.close_pool()
    assert pool.close_count == 1
    assert db.get_pool() is None


async def test_case_e_close_exception_does_not_stuck():
    pool = FakePool(raise_on_close=True)
    db._pool = pool
    # close() 自身抛异常不应向外传播，且 _closing 必须复位
    await db.close_pool()
    assert pool.close_count == 1
    assert db._closing is False
    assert db.get_pool() is None
