"""V3 缺口 1：两类回执的 generation fencing（方案 `docs/plans/plan-v3-unwired-landing-2026-10-15.md` 项 4）。

判据刻意分两层，避免把**结构断言**当成**行为证明**：

- **行为层（真证明）**：``InMemoryAwaitableTaskStore`` 的 fence 是 Python 级比较，可完整验证
  「stale 拒写 / 同代与更新代放行 / 任一侧 None 放行 / 不得把已知 generation 降级」；
  迁移文件被 ``discover()`` 认出且幂等、可回滚。
- **结构层（只证 SQL 形状）**：PG 侧的**原子**拒绝依赖真 PG 执行 WHERE 子句，本机无 PG ⇒
  这里只钉三件事：fence 子句在 SQL 里、generation 进了参数元组、DB 说"没写进去"时必抛
  ``FencedWriteError`` 而不是静默返回。**真 PG 上并发双写被拒属「待环境」判据，不得声称已验证。**
"""

from typing import Any

import pytest

from agent_runtime.awaitable_task import (
    AwaitableKind,
    AwaitableState,
    AwaitableTask,
    InMemoryAwaitableTaskStore,
    is_stale_generation,
)
from agent_runtime.awaitable_task_pg import PgAwaitableTaskStore
from agent_runtime.planner.durability import FencedWriteError
from agent_runtime.planner.durability_pg import PgSideEffectStore

# ===== 替身：镜像 psycopg AsyncConnectionPool 的调用形状 =====
# connection() → async CM → conn.execute(sql, params) → cursor.fetchone()/fetchall()
# 每次 execute 依次消费 results 里的一个结果集（用尽后返回空），以便区分
# 「insert 的 RETURNING」与其后的「has() 判别查询」。


class _Cursor:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    async def fetchone(self):
        return self._rows[0] if self._rows else None

    async def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, pool: "_FakePool") -> None:
        self._pool = pool

    async def execute(self, sql: str, params: Any = None) -> _Cursor:
        self._pool.executed.append((sql, params))
        return _Cursor(self._pool.next_result())


class _ConnCtx:
    def __init__(self, pool: "_FakePool") -> None:
        self._pool = pool

    async def __aenter__(self) -> _Conn:
        return _Conn(self._pool)

    async def __aexit__(self, *exc) -> bool:
        return False


class _FakePool:
    def __init__(self, results: list[list[tuple]] | None = None) -> None:
        self._results = list(results or [])
        self.executed: list[tuple[str, Any]] = []

    def next_result(self) -> list[tuple]:
        return self._results.pop(0) if self._results else []

    def connection(self) -> _ConnCtx:
        return _ConnCtx(self)


def _task(
    task_id: str = "t1",
    state: AwaitableState = AwaitableState.SUBMITTED,
    generation: int | None = None,
) -> AwaitableTask:
    return AwaitableTask(
        execution_id="e1",
        step_id="s1",
        kind=AwaitableKind.EXTERNAL,
        provider="p",
        task_id=task_id,
        state=state,
        generation=generation,
    )


# ===== fence 判据本身 =====


@pytest.mark.parametrize(
    ("current", "incoming", "expected"),
    [
        (5, 3, True),   # 旧 owner（takeover 后落后）→ stale
        (5, 5, False),  # 同代（同 owner 续租）→ 放行
        (5, 6, False),  # 新 owner → 放行
        (None, 5, False),  # 存量行无 generation → 不 fence
        (5, None, False),  # 未接线调用方无 generation → 不 fence
        (None, None, False),
    ],
)
def test_is_stale_generation_truth_table(current, incoming, expected):
    assert is_stale_generation(current, incoming) is expected


# ===== 行为层：InMemory external task receipt =====


async def test_inmemory_rejects_stale_generation_write():
    store = InMemoryAwaitableTaskStore()
    await store.save(_task(generation=5))

    # RUNNING 是 SUBMITTED 的合法后继 ⇒ 拒绝只能来自 fence，不是状态转换校验
    with pytest.raises(FencedWriteError):
        await store.save(_task(state=AwaitableState.RUNNING, generation=4))

    cur = await store.load("t1")
    assert cur.state is AwaitableState.SUBMITTED  # 被拒的写没落地
    assert cur.generation == 5


async def test_inmemory_allows_same_and_newer_generation():
    store = InMemoryAwaitableTaskStore()
    await store.save(_task(generation=5))
    await store.save(_task(state=AwaitableState.RUNNING, generation=5))
    await store.save(_task(state=AwaitableState.COMPLETED, generation=6))

    cur = await store.load("t1")
    assert cur.state is AwaitableState.COMPLETED
    assert cur.generation == 6


async def test_inmemory_unknown_generation_write_does_not_downgrade_fence():
    """无 generation 的写入放行，但不得把已知 generation 抹成 None（否则 fence 被永久解除）。"""
    store = InMemoryAwaitableTaskStore()
    await store.save(_task(generation=5))
    await store.save(_task(state=AwaitableState.RUNNING, generation=None))

    cur = await store.load("t1")
    assert cur.generation == 5
    # 且 fence 仍然有效：此后 stale 写入照旧被拒
    with pytest.raises(FencedWriteError):
        await store.save(_task(state=AwaitableState.COMPLETED, generation=4))


async def test_inmemory_legacy_rows_stay_unfenced():
    """两侧都无 generation（v12 迁移前的存量形态）⇒ 行为与改动前一致，可正常覆盖。"""
    store = InMemoryAwaitableTaskStore()
    await store.save(_task(generation=None))
    await store.save(_task(state=AwaitableState.RUNNING, generation=None))
    assert (await store.load("t1")).state is AwaitableState.RUNNING


def test_generation_is_part_of_the_persisted_shape():
    assert _task(generation=9).to_dict()["generation"] == 9


# ===== 结构层：PG external task receipt =====


async def test_pg_awaitable_rejected_write_raises_fenced_error():
    # results: ① save() 开头的 load() → 无行；② INSERT … RETURNING → 无行（= 被 fence 拒）
    pool = _FakePool(results=[[], []])
    store = PgAwaitableTaskStore(pool)

    with pytest.raises(FencedWriteError):
        await store.save(_task(generation=3))

    insert_sql, insert_params = pool.executed[1]
    assert "EXCLUDED.generation >= awaitable_tasks.generation" in insert_sql
    assert "awaitable_tasks.generation IS NULL OR EXCLUDED.generation IS NULL" in insert_sql
    # 不得用 EXCLUDED.generation 直接覆盖，否则一次无 generation 的写就解除 fence
    assert "COALESCE(EXCLUDED.generation, awaitable_tasks.generation)" in insert_sql
    assert "RETURNING task_id" in insert_sql
    assert insert_params[-1] == 3


async def test_pg_awaitable_accepted_write_does_not_raise():
    pool = _FakePool(results=[[], [("t1",)]])
    await PgAwaitableTaskStore(pool).save(_task(generation=3))


async def test_pg_awaitable_load_maps_generation_column():
    row = (
        "t1", "e1", "s1", "external", "p", "submitted",
        None, None, None, None, None, None, None, "{}", 1.0, 9,
    )
    pool = _FakePool(results=[[row]])
    task = await PgAwaitableTaskStore(pool).load("t1")
    assert task is not None
    assert task.generation == 9
    assert "generation" in pool.executed[0][0]


async def test_pg_awaitable_legacy_row_without_generation_maps_to_none():
    row = (
        "t1", "e1", "s1", "external", "p", "submitted",
        None, None, None, None, None, None, None, "{}", 1.0, None,
    )
    pool = _FakePool(results=[[row]])
    task = await PgAwaitableTaskStore(pool).load("t1")
    assert task.generation is None


# ===== 结构层：PG side effect receipt =====


async def test_pg_side_effect_without_generation_keeps_legacy_shape():
    """generation=None 走原路径：不加 lease 守卫、不多查一次 has()、写不进去只返回 False。"""
    pool = _FakePool(results=[[]])
    store = PgSideEffectStore(pool)

    assert await store.record("e1", "s1", "eff", "owner-a") is False

    sql, params = pool.executed[0]
    assert "execution_leases" not in sql
    assert "ON CONFLICT (effect_key) DO NOTHING" in sql
    assert params[-1] is None
    assert len(pool.executed) == 1  # 未 fence 路径不得多出判别查询


async def test_pg_side_effect_with_generation_guards_on_lease_table():
    pool = _FakePool(results=[[("e1:s1:eff",)]])
    store = PgSideEffectStore(pool)

    assert await store.record("e1", "s1", "eff", "owner-a", generation=7) is True

    sql, params = pool.executed[0]
    # fence 的权威来源是当前 lease 的 generation，且必须与 INSERT 同一条语句（先查再插会竞态）
    assert "execution_leases" in sql
    assert "generation > %s" in sql
    assert "expires_at > now()" in sql
    assert "WHERE NOT EXISTS" in sql
    assert params[-2:] == ("e1", 7)
    assert params[6] == 7  # generation 也落到 side_effects.generation 列（取证用）


async def test_pg_side_effect_fenced_write_raises_instead_of_silent_false():
    """被 fence 拒绝时必须抛错：静默返回 False 会被调用方读成「副作用早已落地」。"""
    pool = _FakePool(results=[[], []])  # INSERT 没写进去，has() 也查不到 ⇒ 只可能是被 fence
    store = PgSideEffectStore(pool)

    with pytest.raises(FencedWriteError):
        await store.record("e1", "s1", "eff", "owner-a", generation=7)

    assert len(pool.executed) == 2  # 第二条是区分「去重 vs 被拒」的 has() 查询


async def test_pg_side_effect_existing_key_returns_false_even_with_generation():
    pool = _FakePool(results=[[], [(1,)]])  # INSERT 去重落空，has() 命中 ⇒ 幂等去重
    store = PgSideEffectStore(pool)
    assert await store.record("e1", "s1", "eff", "owner-a", generation=7) is False


async def test_pg_side_effect_lease_table_is_configurable():
    """表名可配：与 PgExecutionOwnershipStore(table=...) 不同名会让 fence 静默失效。"""
    pool = _FakePool(results=[[("k",)]])
    store = PgSideEffectStore(pool, lease_table="custom_leases")
    await store.record("e1", "s1", "eff", "owner-a", generation=7)
    assert "custom_leases" in pool.executed[0][0]


# ===== 迁移文件 =====


def test_migration_012_is_discovered_idempotent_and_reversible():
    from agent_runtime.migrations.base import discover

    migrations = {m.version: m for m in discover()}
    assert 12 in migrations, "012 迁移未被 discover() 认出（检查文件名约定 NNN_name.up.sql）"
    m = migrations[12]

    up = m.read_up()
    assert up.count("ADD COLUMN IF NOT EXISTS generation BIGINT") == 2
    assert "awaitable_tasks" in up and "side_effects" in up
    # 不得改已应用的迁移文件（001 的 checksum 被 schema_migrations 钉住），
    # 所以本迁移只能是增量 ALTER，不能是 CREATE TABLE。
    assert "CREATE TABLE" not in up

    down = m.read_down()
    assert down is not None, "012 必须可回滚（提供 .down.sql）"
    assert down.count("DROP COLUMN IF EXISTS generation") == 2


def test_migration_012_checksum_is_stable():
    from agent_runtime.migrations.base import discover

    m = {x.version: x for x in discover()}[12]
    assert m.checksum() == m.checksum()
    assert len(m.checksum()) == 16
