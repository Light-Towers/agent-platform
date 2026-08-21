"""PG 持久化后端单元测试（§20 A/B 组：语义 + 并发 CAS 正确性）。

使用 FakePgPool 模拟 psycopg 连接池，验证：
- A 组：Checkpoint / Idempotency / Lease CRUD 语义
- B 组：并发 CAS 单飞、capacity 限流、stale reap 防重复
"""

import asyncio
import json
import time
from typing import Any

import pytest
from agent_runtime.admission_gateway import PgAdmissionController
from agent_runtime.planner.durability import (
    Checkpoint,
    InMemoryCheckpointStore,
    InMemoryExecutionOwnershipStore,
    InMemoryIdempotencyStore,
)
from agent_runtime.planner.durability_pg import (
    PgCheckpointStore,
    PgExecutionOwnershipStore,
    PgIdempotencyStore,
)
from agent_runtime.schemas import ADMISSION_ADMITTED, ADMISSION_QUEUED, ADMISSION_REJECTED

# ===== Fake psycopg Pool 实现 =====

class _FakeCursor:
    """模拟 psycopg AsyncCursor：execute 返回 self，fetchone/fetchall 返回预设结果。"""

    def __init__(self, pool: "_FakePgPool", sql: str, params: tuple):
        self._pool = pool
        self._sql = sql.lower()
        self._params = params
        self._results: list[tuple] = []
        self._idx = 0
        self._execute()

    def _execute(self) -> None:
        sql = self._sql
        params = self._params
        p = self._pool

        # --- execution_checkpoints ---
        if "execution_checkpoints" in sql:
            if "select completed" in sql:
                eid = params[0]
                row = p.checkpoints.get(eid)
                if row:
                    self._results = [(
                        json.dumps(row["completed"]),
                        row["updated_at"],
                        row["resumable"],
                        row.get("checkpoint_version", 1),
                        row.get("graph_id"),
                        row.get("graph_version"),
                        row.get("generation", 0),
                    )]
            elif "insert" in sql and "on conflict" in sql:
                # upsert（§20 新增 checkpoint_version/graph_id/graph_version/generation 字段）
                eid, completed_json, resumable, cpv, gid, gver, gen = params
                completed = json.loads(completed_json)
                p.checkpoints[eid] = {
                    "completed": completed,
                    "updated_at": time.time(),
                    "resumable": bool(resumable),
                    "checkpoint_version": cpv,
                    "graph_id": gid,
                    "graph_version": gver,
                    "generation": gen,
                }
                self._results = [("OK",)]

        # --- idempotency_keys ---
        elif "idempotency_keys" in sql:
            if "select result" in sql:
                key = params[0]
                row = p.idempotency.get(key)
                if row:
                    self._results = [(json.dumps(row),)]
            elif "insert" in sql and "on conflict" in sql:
                key, result_json = params
                p.idempotency[key] = json.loads(result_json)
                self._results = [("OK",)]

        # --- execution_leases ---
        elif "execution_leases" in sql:
            if "insert" in sql and "on conflict" in sql:
                # acquire CAS（§20 返回 (execution_id, generation)）
                eid, owner, ttl_s = params[0], params[1], float(params[2])
                now = time.time()
                cur = p.leases.get(eid)
                if cur is None or cur[1] < now or cur[0] == owner:
                    gen = (cur[2] + 1) if cur is not None else 1
                    p.leases[eid] = (owner, now + ttl_s, gen)
                    self._results = [(eid, gen)]
                else:
                    self._results = []
            elif "update" in sql and "set expires_at" in sql and "where execution_id" in sql and "owner" in sql:
                # heartbeat (no owner check in our simplified impl)
                eid, ttl_s = params[1], float(params[0])
                now = time.time()
                if eid in p.leases:
                    cur_owner, _, cur_gen = p.leases[eid]
                    p.leases[eid] = (cur_owner, now + ttl_s, cur_gen)
                    self._results = [(eid,)]
                else:
                    self._results = []
            elif "delete" in sql and "where execution_id" in sql and "owner" in sql:
                # release
                eid, owner = params
                cur = p.leases.get(eid)
                if cur is not None and cur[0] == owner:
                    del p.leases[eid]
                    self._results = [("DELETE 1",)]
                else:
                    self._results = [("DELETE 0",)]
            elif "select owner" in sql and "where execution_id" in sql and "expires_at > now" in sql:
                # get_owner
                eid = params[0]
                cur = p.leases.get(eid)
                now = time.time()
                if cur is not None and cur[1] > now:
                    self._results = [(cur[0],)]
                else:
                    self._results = []
            elif "select execution_id" in sql and "expires_at <=" in sql:
                # list_stale
                now = time.time()
                self._results = [(eid,) for eid, (_, exp, _) in p.leases.items() if exp <= now]
            elif "update" in sql and "set owner = null" in sql and "expires_at <=" in sql:
                # reap_stale_notifying
                now = time.time()
                reclaimed = [eid for eid, (_, exp) in p.leases.items() if exp <= now]
                for eid in reclaimed:
                    p.leases[eid] = ("", 0)
                self._results = [(eid,) for eid in reclaimed]

        # --- admission_slots ---
        elif "admission_slots" in sql:
            if "insert into admission_slots" in sql and "select count" in sql:
                # _try_acquire_slot CAS
                slot_key, eid, owner, ttl_s, capacity = params
                # 简化：只检查当前活跃数
                active = sum(1 for exp in p.slots.values() if exp > time.time())
                if active < capacity:
                    p.slots[eid] = time.time() + float(ttl_s)
                    self._results = [(slot_key,)]
                else:
                    self._results = []
            elif "delete from admission_slots" in sql and "execution_id" in sql:
                # mark_completed
                eid = params[0]
                if eid in p.slots:
                    del p.slots[eid]
                self._results = [("DELETE 1",)]

        # --- notify ---
        elif "notify" in sql:
            self._results = [("OK",)]

    async def fetchone(self):
        if self._idx < len(self._results):
            row = self._results[self._idx]
            self._idx += 1
            return row
        return None

    async def fetchall(self):
        rows = self._results[self._idx:]
        self._idx = len(self._results)
        return rows

    @property
    def rowcount(self):
        return len(self._results)


class _FakeConnection:
    def __init__(self, pool: "_FakePgPool"):
        self._pool = pool
        self._notifies = asyncio.Queue()

    async def execute(self, sql: str, params: tuple = ()):
        return _FakeCursor(self._pool, sql, params)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakePgPool:
    """模拟 psycopg AsyncConnectionPool：connection() 返回 _FakeConnection。"""

    def __init__(self):
        self.checkpoints: dict[str, dict] = {}
        self.idempotency: dict[str, Any] = {}
        self.leases: dict[str, tuple[str, float]] = {}  # execution_id -> (owner, expires_at)
        self.slots: dict[str, float] = {}  # execution_id -> expires_at

    def connection(self):
        return _FakeConnection(self)

    async def close(self):
        pass


# ===== A 组：单元语义 =====

class TestPgCheckpointStore:
    @pytest.mark.asyncio
    async def test_crud(self):
        pool = _FakePgPool()
        store = PgCheckpointStore(pool)

        cp = Checkpoint(execution_id="e1", completed={"node1": "result1"}, resumable=False)
        await store.save(cp)

        loaded = await store.load("e1")
        assert loaded is not None
        assert loaded.execution_id == "e1"
        assert loaded.completed == {"node1": "result1"}
        assert loaded.resumable is False

        # update
        cp.resumable = True
        await store.save(cp)
        loaded = await store.load("e1")
        assert loaded.resumable is True

        # miss
        assert await store.load("nonexistent") is None


class TestPgIdempotencyStore:
    @pytest.mark.asyncio
    async def test_crud(self):
        pool = _FakePgPool()
        store = PgIdempotencyStore(pool)

        await store.save("key1", {"answer": "42"})
        val = await store.get("key1")
        assert val == {"answer": "42"}

        # overwrite
        await store.save("key1", {"answer": "99"})
        val = await store.get("key1")
        assert val == {"answer": "99"}

        assert await store.get("missing") is None


class TestPgExecutionOwnershipStore:
    @pytest.mark.asyncio
    async def test_acquire_release(self):
        pool = _FakePgPool()
        store = PgExecutionOwnershipStore(pool)

        # 首次获取
        ok, _ = await store.acquire("e1", "owner1", 10.0)
        assert ok is True

        # 同 owner 再次获取（heartbeat 语义）应成功
        ok, _ = await store.acquire("e1", "owner1", 10.0)
        assert ok is True

        # 不同 owner 在租约内获取应失败
        ok, _ = await store.acquire("e1", "owner2", 10.0)
        assert ok is False

        # 释放
        await store.release("e1", "owner1")
        # 释放后可被他人获取
        ok, _ = await store.acquire("e1", "owner2", 10.0)
        assert ok is True

    @pytest.mark.asyncio
    async def test_heartbeat(self):
        pool = _FakePgPool()
        store = PgExecutionOwnershipStore(pool)
        await store.acquire("e1", "owner1", 10.0)
        await store.heartbeat("e1", 20.0)
        owner = await store.get_owner("e1")
        assert owner == "owner1"

    @pytest.mark.asyncio
    async def test_get_owner_expiry(self):
        pool = _FakePgPool()
        store = PgExecutionOwnershipStore(pool)
        await store.acquire("e1", "owner1", 0.01)
        assert await store.get_owner("e1") == "owner1"
        await asyncio.sleep(0.02)
        assert await store.get_owner("e1") is None

    @pytest.mark.asyncio
    async def test_list_stale(self):
        pool = _FakePgPool()
        store = PgExecutionOwnershipStore(pool)
        await store.acquire("e1", "o1", 0.01)
        await store.acquire("e2", "o2", 10.0)
        await asyncio.sleep(0.02)
        stale = await store.list_stale(time.time())
        assert "e1" in stale
        assert "e2" not in stale


# ===== B 组：并发 CAS 正确性 =====

class TestConcurrentLeaseAcquire:
    """10 worker 同时 acquire 同一 execution → 成功者恰 1，失败者 9。"""

    @pytest.mark.asyncio
    async def test_cas_single_flight(self):
        pool = _FakePgPool()
        store = PgExecutionOwnershipStore(pool)

        async def try_acquire(worker_id: int) -> bool:
            return (await store.acquire("shared_exec", f"worker_{worker_id}", 300.0))[0]

        results = await asyncio.gather(*[try_acquire(i) for i in range(10)])
        assert sum(results) == 1  # 仅 1 个成功

        owner = await store.get_owner("shared_exec")
        assert owner is not None
        assert owner.startswith("worker_")


class TestAdmissionCapacityLimit:
    """limit=5 下 100 并发 → 任意时刻 active <= 5。"""

    @pytest.mark.asyncio
    async def test_capacity_limit(self):
        pool = _FakePgPool()
        controller = PgAdmissionController(pool, capacity=5, timeout_s=10.0)

        async def try_enqueue(i: int):
            return await controller.enqueue(f"req_{i}", f"s_{i%3}", f"u_{i%5}")

        decisions = await asyncio.gather(*[try_enqueue(i) for i in range(100)])
        admitted = [d for d in decisions if d.status == ADMISSION_ADMITTED]
        queued = [d for d in decisions if d.status == ADMISSION_QUEUED]
        # 活跃数不超过 capacity
        assert len(admitted) == 5
        assert len(queued) == 95


class TestStaleReapPreventsDuplicate:
    """stale claim 多副本并发发现 → 只有 winner-take-all 认领，不重复（§20 G1）。

    注：PgExecutionOwnershipStore.claim_stale 的真 PG 行为（FOR UPDATE SKIP LOCKED）
    由 tests/test_multi_replica_recovery.py::test_concurrent_claim_fencing 覆盖；
    此处用 InMemory 实现验证并发 claim 语义等价，避免 mock SQL 重复实现。
    """

    @pytest.mark.asyncio
    async def test_claim_cas_prevents_duplicate(self):
        store = InMemoryExecutionOwnershipStore()
        cp_store = InMemoryCheckpointStore()

        # 制造 2 个 stale execution（短 ttl + 过期）
        await store.acquire("e1", "o1", 0.01)
        await store.acquire("e2", "o2", 0.01)
        await cp_store.save(Checkpoint("e1", {"n": "r1"}))
        await cp_store.save(Checkpoint("e2", {"n": "r2"}))
        await asyncio.sleep(0.02)

        # 两个副本（B1 / B2）并发 claim 同一组 stale
        r1, r2 = await asyncio.gather(
            store.claim_stale("B1", 10.0),
            store.claim_stale("B2", 10.0),
        )
        claimed = dict(r1) | dict(r2)  # execution_id -> generation
        # 每个 execution 只应被一个副本认领（winner-take-all）
        assert "e1" in claimed and "e2" in claimed
        winners = [who for who, res in (("B1", r1), ("B2", r2)) if any(e == "e1" for e, _ in res)]
        assert len(winners) == 1
        winners2 = [who for who, res in (("B1", r1), ("B2", r2)) if any(e == "e2" for e, _ in res)]
        assert len(winners2) == 1


class TestInMemoryEquivalence:
    """验证 InMemory 实现语义与 PG 实现一致（回归保护）。"""

    @pytest.mark.asyncio
    async def test_checkpoint_equivalence(self):
        mem = InMemoryCheckpointStore()
        pg = PgCheckpointStore(_FakePgPool())

        cp = Checkpoint("e1", {"n": "v"})
        await mem.save(cp)
        await pg.save(cp)

        m = await mem.load("e1")
        p = await pg.load("e1")
        assert m.completed == p.completed

    @pytest.mark.asyncio
    async def test_idempotency_equivalence(self):
        mem = InMemoryIdempotencyStore()
        pg = PgIdempotencyStore(_FakePgPool())

        await mem.save("k", "v1")
        await pg.save("k", "v1")
        assert await mem.get("k") == await pg.get("k")

    @pytest.mark.asyncio
    async def test_ownership_equivalence(self):
        mem = InMemoryExecutionOwnershipStore()
        pg = PgExecutionOwnershipStore(_FakePgPool())

        # acquire 返回 (granted, generation)，比较 granted 部分
        assert (await mem.acquire("e1", "o1", 10))[0] == (await pg.acquire("e1", "o1", 10))[0]
        assert not (await mem.acquire("e1", "o2", 10))[0]
        assert not (await pg.acquire("e1", "o2", 10))[0]
        await mem.release("e1", "o1")
        await pg.release("e1", "o1")
        assert (await mem.acquire("e1", "o2", 10))[0]
        assert (await pg.acquire("e1", "o2", 10))[0]


# ===== 并发 admission wait_for_admit 测试 =====

class TestPgAdmissionWaitForAdmit:
    @pytest.mark.asyncio
    async def test_wait_for_admit_promotes_queued(self):
        pool = _FakePgPool()
        ctrl = PgAdmissionController(pool, capacity=2, timeout_s=5.0)

        # 占满 capacity
        d1 = await ctrl.enqueue("r1", "s1", "u1")
        d2 = await ctrl.enqueue("r2", "s2", "u2")
        assert d1.status == ADMISSION_ADMITTED
        assert d2.status == ADMISSION_ADMITTED

        # 第 3 个进入排队
        d3 = await ctrl.enqueue("r3", "s3", "u3")
        assert d3.status == ADMISSION_QUEUED

        # r1 完成，释放槽位
        await ctrl.mark_completed("r1")

        # r3 应在 wait_for_admit 中被 promoted
        d3_final = await ctrl.wait_for_admit("r3")
        assert d3_final.status == ADMISSION_ADMITTED

    @pytest.mark.asyncio
    async def test_wait_for_admit_timeout(self):
        pool = _FakePgPool()
        ctrl = PgAdmissionController(pool, capacity=1, timeout_s=0.05)

        d1 = await ctrl.enqueue("r1", "s1", "u1")
        assert d1.status == ADMISSION_ADMITTED

        d2 = await ctrl.enqueue("r2", "s2", "u2")
        assert d2.status == ADMISSION_QUEUED

        # 不释放 r1，等待超时
        d2_final = await ctrl.wait_for_admit("r2")
        assert d2_final.status == ADMISSION_REJECTED
        assert d2_final.reason == "ADMISSION_TIMEOUT"


# ===== 入口 =====

if __name__ == "__main__":
    pytest.main([__file__, "-v"])