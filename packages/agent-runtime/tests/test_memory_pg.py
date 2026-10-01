"""四类 Memory PG 持久化后端单测。

用 fake pool 验证 PgEpisodicStore / PgProceduralStore 的 SQL 逻辑。
"""

import json

from agent_runtime.episodic_memory import Episode, EpisodeOutcome
from agent_runtime.memory_pg import PgEpisodicStore, PgProceduralStore
from agent_runtime.procedural_memory import ProceduralEntry

# 隔离域（plan T1）：store 方法必显式传 tenant_id（无 'default' 兜底）。
TENANT = "t-pg"

# ===== Fake Pool（psycopg 风格） =====

class _FakeCursor:
    def __init__(self, pool, sql, params):
        self._pool = pool
        self._sql = sql.lower()
        self._params = params
        self._results: list[tuple] = []
        self._execute()

    def _execute(self):
        sql = self._sql
        p = self._pool
        params = self._params

        if "episodic_memories" in sql:
            if "insert" in sql:
                # (tenant_id, episode_id, execution_id, task_summary, outcome, key_steps,
                #  lessons, skill_names, total_tokens, total_cost, duration, importance,
                #  created_at, metadata)
                tenant, eid = params[0], params[1]
                row = {
                    "tenant_id": tenant,
                    "episode_id": eid, "execution_id": params[2], "task_summary": params[3],
                    "outcome": params[4], "key_steps": json.loads(params[5]),
                    "lessons": json.loads(params[6]), "skill_names": json.loads(params[7]),
                    "total_tokens": params[8], "total_cost": params[9], "duration": params[10],
                    "importance": params[11], "created_at": params[12],
                    "metadata": json.loads(params[13]),
                }
                p.episodic[(tenant, eid)] = row
                self._results = [(eid,)]
            elif "select" in sql and "where episode_id" in sql:
                tenant, eid = params[1], params[0]
                row = p.episodic.get((tenant, eid))
                if row:
                    self._results = [self._ep_row(row)]
            elif "select" in sql and "where execution_id" in sql:
                tenant, execution_id = params[1], params[0]
                rows = [
                    r for (t, _e), r in p.episodic.items()
                    if t == tenant and r["execution_id"] == execution_id
                ]
                self._results = [self._ep_row(r) for r in rows]
            elif "select" in sql and "ilike" in sql:
                # WHERE tenant_id = %s AND (task_summary ILIKE %s OR ...) params (tenant, q, q, k)
                tenant, query = params[0], params[1]
                rows = [
                    r for (t, _e), r in p.episodic.items()
                    if t == tenant and query.strip("%") in r["task_summary"]
                ]
                self._results = [self._ep_row(r) for r in rows]
            elif "select" in sql:
                # list_all: WHERE tenant_id = %s ... params (tenant, limit)
                tenant = params[0]
                rows = [r for (t, _e), r in p.episodic.items() if t == tenant]
                self._results = [self._ep_row(r) for r in rows]
            elif "delete" in sql:
                tenant, eid = params[1], params[0]
                if (tenant, eid) in p.episodic:
                    del p.episodic[(tenant, eid)]
                    self._results = [(eid,)]
                else:
                    self._results = []

        elif "procedural_memories" in sql:
            if "insert" in sql:
                # (tenant_id, name, version, kind, description, input_schema, output_schema,
                #  effect_contract, lifecycle, definition, created_at, updated_at)
                tenant, name, version = params[0], params[1], params[2]
                row = {
                    "tenant_id": tenant,
                    "name": name, "version": version, "kind": params[3],
                    "description": params[4],
                    "input_schema": json.loads(params[5]) if params[5] else None,
                    "output_schema": json.loads(params[6]) if params[6] else None,
                    "effect_contract": json.loads(params[7]) if params[7] else None,
                    "lifecycle": params[8],
                    "definition": json.loads(params[9]),
                    "created_at": params[10], "updated_at": params[11],
                }
                p.procedural[(tenant, name, version)] = row
                self._results = [(name, version)]
            elif "select" in sql and "where tenant_id = %s and name = %s and version" in sql:
                tenant, name, version = params[0], params[1], params[2]
                row = p.procedural.get((tenant, name, version))
                if row:
                    self._results = [self._proc_row(row)]
            elif "select" in sql and "where tenant_id = %s and name = %s" in sql:
                tenant, name = params[0], params[1]
                rows = [r for (t, n, _v), r in p.procedural.items() if t == tenant and n == name]
                if "order by" in sql and "case lifecycle" in sql:
                    rows.sort(key=lambda r: r["version"], reverse=True)
                    rows.sort(key=lambda r: 0 if r["lifecycle"] == "stable" else 1)
                    rows = rows[:1]
                else:
                    rows.sort(key=lambda r: r["version"], reverse=True)
                self._results = [self._proc_row(r) for r in rows]
            elif "select" in sql:
                # list_all: WHERE tenant_id = %s params (tenant,)
                tenant = params[0]
                rows = [r for (t, _n, _v), r in p.procedural.items() if t == tenant]
                self._results = [self._proc_row(r) for r in rows]
            elif "delete" in sql:
                tenant, name, version = params[0], params[1], params[2]
                key = (tenant, name, version)
                if key in p.procedural:
                    del p.procedural[key]
                    self._results = [(name, version)]

    @staticmethod
    def _ep_row(row):
        return (
            row["episode_id"], row["execution_id"], row["task_summary"], row["outcome"],
            json.dumps(row["key_steps"]), json.dumps(row["lessons"]),
            json.dumps(row["skill_names"]), row["total_tokens"], row["total_cost"],
            row["duration"], row["importance"], row["created_at"],
            json.dumps(row["metadata"]),
        )

    @staticmethod
    def _proc_row(row):
        return (
            row["name"], row["version"], row["kind"], row["description"],
            json.dumps(row["input_schema"]) if row["input_schema"] else None,
            json.dumps(row["output_schema"]) if row["output_schema"] else None,
            json.dumps(row["effect_contract"]) if row["effect_contract"] else None,
            row["lifecycle"], json.dumps(row["definition"]),
            row["created_at"], row["updated_at"],
        )

    async def fetchone(self):
        return self._results[0] if self._results else None

    async def fetchall(self):
        return self._results

    @property
    def rowcount(self):
        return len(self._results)


class _FakeConnection:
    def __init__(self, pool):
        self._pool = pool

    async def execute(self, sql, params=()):
        return _FakeCursor(self._pool, sql, params)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class _FakePgPool:
    def __init__(self):
        self.episodic: dict[tuple[str, str], dict] = {}
        self.procedural: dict[tuple[str, str, str], dict] = {}

    def connection(self):
        return _FakeConnection(self)


# ===== PgEpisodicStore =====

async def test_pg_episodic_save_and_get():
    pool = _FakePgPool()
    store = PgEpisodicStore(pool)

    ep = Episode(
        episode_id="ep1", execution_id="e1", task_summary="招商分析",
        outcome=EpisodeOutcome.SUCCESS, key_steps=["query", "analyze"],
        importance=0.9,
    )
    await store.save(ep, tenant_id=TENANT)
    loaded = await store.get("ep1", tenant_id=TENANT)
    assert loaded is not None
    assert loaded.task_summary == "招商分析"
    assert loaded.outcome is EpisodeOutcome.SUCCESS


async def test_pg_episodic_recall():
    pool = _FakePgPool()
    store = PgEpisodicStore(pool)

    await store.save(Episode(
        episode_id="ep1", execution_id="e1", task_summary="招商分析",
        outcome=EpisodeOutcome.SUCCESS, importance=0.9,
    ), tenant_id=TENANT)
    await store.save(Episode(
        episode_id="ep2", execution_id="e2", task_summary="SQL查询",
        outcome=EpisodeOutcome.SUCCESS, importance=0.5,
    ), tenant_id=TENANT)

    results = await store.recall("招商", tenant_id=TENANT)
    assert len(results) == 1
    assert results[0].task_summary == "招商分析"


async def test_pg_episodic_recall_cross_tenant_empty():
    """plan T1：tenantA 写入，tenantB recall 空（真实 SQL 谓词经 fake 生效）。"""
    pool = _FakePgPool()
    store = PgEpisodicStore(pool)
    await store.save(Episode(
        episode_id="ep1", execution_id="e1", task_summary="tenantA招商",
        importance=0.9,
    ), tenant_id="tA")
    assert await store.recall("tenantA招商", tenant_id="tB") == []
    assert len(await store.recall("tenantA招商", tenant_id="tA")) == 1


async def test_pg_episodic_list_by_execution():
    pool = _FakePgPool()
    store = PgEpisodicStore(pool)

    await store.save(Episode(episode_id="ep1", execution_id="e1", task_summary="a"), tenant_id=TENANT)
    await store.save(Episode(episode_id="ep2", execution_id="e1", task_summary="b"), tenant_id=TENANT)
    await store.save(Episode(episode_id="ep3", execution_id="e2", task_summary="c"), tenant_id=TENANT)

    results = await store.list_by_execution("e1", tenant_id=TENANT)
    assert len(results) == 2


# ===== PgProceduralStore =====

async def test_pg_procedural_save_and_load():
    pool = _FakePgPool()
    store = PgProceduralStore(pool)

    entry = ProceduralEntry(
        name="search", version="1.0.0", kind="function",
        description="向量搜索", lifecycle="stable",
    )
    await store.save(entry, tenant_id=TENANT)
    loaded = await store.load("search", "1.0.0", tenant_id=TENANT)
    assert loaded is not None
    assert loaded.description == "向量搜索"


async def test_pg_procedural_load_latest_stable():
    pool = _FakePgPool()
    store = PgProceduralStore(pool)

    await store.save(ProceduralEntry(
        name="search", version="1.0.0", kind="function",
        description="v1", lifecycle="stable",
    ), tenant_id=TENANT)
    await store.save(ProceduralEntry(
        name="search", version="2.0.0", kind="function",
        description="v2", lifecycle="stable",
    ), tenant_id=TENANT)

    loaded = await store.load("search", tenant_id=TENANT)
    assert loaded is not None
    assert loaded.version == "2.0.0"


async def test_pg_procedural_list_all():
    pool = _FakePgPool()
    store = PgProceduralStore(pool)

    await store.save(ProceduralEntry(name="a", version="1.0", kind="function", description=""), tenant_id=TENANT)
    await store.save(ProceduralEntry(name="b", version="1.0", kind="function", description=""), tenant_id=TENANT)
    assert len(await store.list_all(tenant_id=TENANT)) == 2


async def test_pg_procedural_cross_tenant_isolated():
    """plan T1：同 (name, version) 两租户各一行、互不可见（PK 命名空间化）。"""
    pool = _FakePgPool()
    store = PgProceduralStore(pool)
    await store.save(ProceduralEntry(name="auto_x", version="auto", kind="function", description="A"), tenant_id="tA")
    await store.save(ProceduralEntry(name="auto_x", version="auto", kind="function", description="B"), tenant_id="tB")
    assert (await store.load("auto_x", "auto", tenant_id="tA")).description == "A"
    assert (await store.load("auto_x", "auto", tenant_id="tB")).description == "B"
    assert len(await store.list_all(tenant_id="tA")) == 1


async def test_pg_procedural_delete():
    pool = _FakePgPool()
    store = PgProceduralStore(pool)

    await store.save(ProceduralEntry(name="search", version="1.0", kind="function", description=""), tenant_id=TENANT)
    assert await store.delete("search", "1.0", tenant_id=TENANT) is True
    assert await store.load("search", "1.0", tenant_id=TENANT) is None
