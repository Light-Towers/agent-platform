"""四类 Memory PG 持久化后端单测。

用 fake pool 验证 PgEpisodicStore / PgProceduralStore 的 SQL 逻辑。
"""

import json

from agent_runtime.episodic_memory import Episode, EpisodeOutcome
from agent_runtime.memory_pg import PgEpisodicStore, PgProceduralStore
from agent_runtime.procedural_memory import ProceduralEntry

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
                eid = params[0]
                row = {
                    "episode_id": eid, "execution_id": params[1], "task_summary": params[2],
                    "outcome": params[3], "key_steps": json.loads(params[4]),
                    "lessons": json.loads(params[5]), "skill_names": json.loads(params[6]),
                    "total_tokens": params[7], "total_cost": params[8], "duration": params[9],
                    "importance": params[10], "created_at": params[11],
                    "metadata": json.loads(params[12]),
                }
                p.episodic[eid] = row
                self._results = [(eid,)]
            elif "select" in sql and "where episode_id" in sql:
                row = p.episodic.get(params[0])
                if row:
                    self._results = [self._ep_row(row)]
            elif "select" in sql and "where execution_id" in sql:
                rows = [r for r in p.episodic.values() if r["execution_id"] == params[0]]
                self._results = [self._ep_row(r) for r in rows]
            elif "select" in sql and "ilike" in sql:
                query = params[0]
                rows = [r for r in p.episodic.values() if query.strip("%") in r["task_summary"]]
                self._results = [self._ep_row(r) for r in rows]
            elif "select" in sql:
                rows = list(p.episodic.values())
                self._results = [self._ep_row(r) for r in rows]
            elif "delete" in sql:
                eid = params[0]
                if eid in p.episodic:
                    del p.episodic[eid]
                    self._results = [(eid,)]
                else:
                    self._results = []

        elif "procedural_memories" in sql:
            if "insert" in sql:
                name, version = params[0], params[1]
                row = {
                    "name": name, "version": version, "kind": params[2],
                    "description": params[3],
                    "input_schema": json.loads(params[4]) if params[4] else None,
                    "output_schema": json.loads(params[5]) if params[5] else None,
                    "effect_contract": json.loads(params[6]) if params[6] else None,
                    "lifecycle": params[7],
                    "definition": json.loads(params[8]),
                    "created_at": params[9], "updated_at": params[10],
                }
                p.procedural[(name, version)] = row
                self._results = [(name, version)]
            elif "select" in sql and "where name = %s and version" in sql:
                key = (params[0], params[1])
                row = p.procedural.get(key)
                if row:
                    self._results = [self._proc_row(row)]
            elif "select" in sql and "where name = %s" in sql:
                name = params[0]
                rows = [r for (n, v), r in p.procedural.items() if n == name]
                if "order by" in sql and "case lifecycle" in sql:
                    rows.sort(key=lambda r: r["version"], reverse=True)
                    rows.sort(key=lambda r: 0 if r["lifecycle"] == "stable" else 1)
                    rows = rows[:1]
                else:
                    rows.sort(key=lambda r: r["version"], reverse=True)
                self._results = [self._proc_row(r) for r in rows]
            elif "select" in sql:
                rows = list(p.procedural.values())
                self._results = [self._proc_row(r) for r in rows]
            elif "delete" in sql:
                key = (params[0], params[1])
                if key in p.procedural:
                    del p.procedural[key]
                    self._results = [(key[0], key[1])]

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
        self.episodic: dict[str, dict] = {}
        self.procedural: dict[tuple[str, str], dict] = {}

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
    await store.save(ep)
    loaded = await store.get("ep1")
    assert loaded is not None
    assert loaded.task_summary == "招商分析"
    assert loaded.outcome is EpisodeOutcome.SUCCESS


async def test_pg_episodic_recall():
    pool = _FakePgPool()
    store = PgEpisodicStore(pool)

    await store.save(Episode(
        episode_id="ep1", execution_id="e1", task_summary="招商分析",
        outcome=EpisodeOutcome.SUCCESS, importance=0.9,
    ))
    await store.save(Episode(
        episode_id="ep2", execution_id="e2", task_summary="SQL查询",
        outcome=EpisodeOutcome.SUCCESS, importance=0.5,
    ))

    results = await store.recall("招商")
    assert len(results) == 1
    assert results[0].task_summary == "招商分析"


async def test_pg_episodic_list_by_execution():
    pool = _FakePgPool()
    store = PgEpisodicStore(pool)

    await store.save(Episode(episode_id="ep1", execution_id="e1", task_summary="a"))
    await store.save(Episode(episode_id="ep2", execution_id="e1", task_summary="b"))
    await store.save(Episode(episode_id="ep3", execution_id="e2", task_summary="c"))

    results = await store.list_by_execution("e1")
    assert len(results) == 2


# ===== PgProceduralStore =====

async def test_pg_procedural_save_and_load():
    pool = _FakePgPool()
    store = PgProceduralStore(pool)

    entry = ProceduralEntry(
        name="search", version="1.0.0", kind="function",
        description="向量搜索", lifecycle="stable",
    )
    await store.save(entry)
    loaded = await store.load("search", "1.0.0")
    assert loaded is not None
    assert loaded.description == "向量搜索"


async def test_pg_procedural_load_latest_stable():
    pool = _FakePgPool()
    store = PgProceduralStore(pool)

    await store.save(ProceduralEntry(
        name="search", version="1.0.0", kind="function",
        description="v1", lifecycle="stable",
    ))
    await store.save(ProceduralEntry(
        name="search", version="2.0.0", kind="function",
        description="v2", lifecycle="stable",
    ))

    loaded = await store.load("search")
    assert loaded is not None
    assert loaded.version == "2.0.0"


async def test_pg_procedural_list_all():
    pool = _FakePgPool()
    store = PgProceduralStore(pool)

    await store.save(ProceduralEntry(name="a", version="1.0", kind="function", description=""))
    await store.save(ProceduralEntry(name="b", version="1.0", kind="function", description=""))
    assert len(await store.list_all()) == 2


async def test_pg_procedural_delete():
    pool = _FakePgPool()
    store = PgProceduralStore(pool)

    await store.save(ProceduralEntry(name="search", version="1.0", kind="function", description=""))
    assert await store.delete("search", "1.0") is True
    assert await store.load("search", "1.0") is None
