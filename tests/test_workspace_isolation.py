"""优化 G 隔离正确性测试：验证 workspace_id 在 RAG 与长期记忆两路真正互不串扰。

不连真实 PG：用带内存分桶存储 + SQL 调用记录的 fake psycopg 池，断言：
- add_document / remember_fact 写入时把 workspace_id 编入 INSERT；
- _vector_ids / _bm25_ids / recall_typed 的查询把 workspace_id 编入 WHERE；
- 端到端：某 workspace 的检索/召回结果里绝不包含另一 workspace 的内容
  （隔离正确性；不依赖 BM25 评分阈值，仅验证"不串扰"）。
符合本仓库 tests/ 基线（全 mock/fake，零环境依赖，可 CI）。
"""

import pytest

from agent_server.config import get_settings
from agent_server.memory import memory_backend as mb
from agent_server.rag import store as rag_store


# ---------------------------------------------------------------------------
# fake psycopg 池：内存分桶（按 workspace_id）+ 记录所有 execute 调用
# ---------------------------------------------------------------------------
class _FakeCur:
    def __init__(self, db, sql, params, log):
        self._db = db
        self._sql = sql
        self._params = params or ()
        self._log = log
        self.rowcount = 0

    async def fetchall(self):
        sql = self._sql
        p = self._params
        if "FROM chunks" in sql and "COUNT" not in sql and "SELECT id, content" in sql:
            ws = p[0]
            return [(r["id"], r["content"]) for r in self._db["chunks"] if r["workspace_id"] == ws]
        if "FROM chunks" in sql and "COUNT" in sql:
            ws = p[0]
            rows = [r for r in self._db["chunks"] if r["workspace_id"] == ws]
            return [(len(rows), max([r["id"] for r in rows], default=0))]
        if "FROM chunks" in sql and "id = ANY" in sql:
            ids, ws = p[0], p[1]
            return [
                (r["id"], r["source"], r["heading"], r["content"])
                for r in self._db["chunks"]
                if r["id"] in set(ids) and r["workspace_id"] == ws
            ]
        if "FROM memories" in sql and "COUNT" not in sql:
            ws = p[0]
            return [
                (r["content"], r["memory_type"], r["importance"], r["created_at"])
                for r in self._db["memories"] if r["user_id"] == ws
            ]
        return []

    async def fetchone(self):
        rows = await self.fetchall()
        return rows[0] if rows else None

    async def execute(self, *a, **k):
        return None


class _FakeConnWriter:
    def __init__(self, db, log):
        self._db = db
        self._log = log

    def cursor(self):
        # store.add_document 现用 conn.cursor().executemany(...)，mock 复用本对象的 executemany
        return self

    async def execute(self, sql, params=None):
        sql = sql.strip()
        p = params or ()
        self._log.append((sql, p))
        if sql.startswith("INSERT INTO chunks"):
            self._db["chunks"].append({
                "id": len(self._db["chunks"]) + 1,
                "doc_id": p[0], "source": p[1], "heading": p[2],
                "content": p[3], "embedding": p[4], "workspace_id": p[5],
            })
            return _FakeCur(self._db, sql, p, self._log)
        if sql.startswith("INSERT INTO memories"):
            self._db["memories"].append({
                "id": len(self._db["memories"]) + 1,
                "user_id": p[0], "content": p[1], "embedding": p[2],
                "memory_type": p[3], "importance": p[4], "created_at": None,
            })
            return _FakeCur(self._db, sql, p, self._log)
        if sql.startswith("DELETE FROM memories"):
            ws = p[0]
            before = len(self._db["memories"])
            self._db["memories"] = [m for m in self._db["memories"] if m["user_id"] != ws]
            cur = _FakeCur(self._db, sql, p, self._log)
            cur.rowcount = before - len(self._db["memories"])
            return cur
        return _FakeCur(self._db, sql, p, self._log)

    async def executemany(self, sql, params_list):
        self._log.append((sql.strip(), tuple(params_list[0] if params_list else ())))
        for p in params_list:
            self._db["chunks"].append({
                "id": len(self._db["chunks"]) + 1,
                "doc_id": p[0], "source": p[1], "heading": p[2],
                "content": p[3], "embedding": p[4], "workspace_id": p[5],
            })
        return None


class _FakeConnCtx:
    def __init__(self, db, log):
        self._db = db
        self._log = log

    async def __aenter__(self):
        return _FakeConnWriter(self._db, self._log)

    async def __aexit__(self, *a):
        return False


class _FakePool:
    def __init__(self):
        self._db = {"chunks": [], "memories": []}
        self.calls = []  # 记录所有 (sql, params)

    def connection(self):
        return _FakeConnCtx(self._db, self.calls)


# ---------------------------------------------------------------------------
# 测试
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def patch_embed(monkeypatch):
    async def _fake_texts(texts, dim=512):
        return [[0.0] * dim for _ in texts]

    async def _fake_query(text, dim=512):
        return [0.0] * dim

    monkeypatch.setattr("app.rag.embed.embed_texts", _fake_texts)
    monkeypatch.setattr("app.rag.embed.embed_query", _fake_query)
    monkeypatch.setattr(mb, "embed_memory", lambda t: [0.0] * 512)
    s = get_settings()
    original_url = s.database_url
    s.memory_extraction_enabled = True
    # 置非空 database_url，使 add_document / vector_search 走真实 SQL 路径
    # （由本测试的 fake psycopg 池接手，不连真实 PG）
    s.database_url = "postgresql://fake/fake"
    monkeypatch.setattr("app.config.get_settings", lambda: s)
    yield
    s.database_url = original_url  # 还原，避免影响同进程其他测试


def _calls_with(pool, substr):
    return [params for sql, params in pool.calls if substr in sql]


async def test_rag_insert_carries_workspace_id(patch_embed):
    pool = _FakePool()
    from agent_server.rag.chunker import Chunk

    await rag_store.add_document(pool, "s.txt", [Chunk(text="内容A", heading="h")], workspace_id="wsA")
    inserts = _calls_with(pool, "INSERT INTO chunks")
    assert inserts, "add_document 应执行 INSERT INTO chunks"
    # 最后一个是 workspace_id 列值
    assert inserts[-1][-1] == "wsA"


async def test_rag_queries_scoped_to_workspace(patch_embed):
    pool = _FakePool()
    # 直接验证 _vector_ids / _bm25_ids 把 workspace_id 编入 WHERE
    await rag_store._vector_ids(pool, [0.0] * 512, 5, "wsX")
    await rag_store._bm25_ids(pool, "关键词", 5, "wsX")
    where_ws = [p for sql, p in pool.calls if "workspace_id" in sql]
    assert where_ws, "检索 SQL 应含 workspace_id WHERE"
    # 所有带 workspace_id 的查询参数都包含 wsX（vector_search 把 ws 放在 where_params 前部）
    assert all("wsX" in p for p in where_ws)


async def test_rag_no_cross_contamination(patch_embed):
    pool = _FakePool()
    from agent_server.rag.chunker import Chunk

    await rag_store.add_document(pool, "a.txt", [Chunk(text="A专有内容", heading="h")], workspace_id="wsA")
    await rag_store.add_document(pool, "b.txt", [Chunk(text="B专有内容", heading="h")], workspace_id="wsB")

    res_b = await rag_store.retrieve_chunks(pool, "内容", k=5, workspace_id="wsB")
    # 隔离正确性：wsB 的结果里绝不含 wsA 的内容（无论 BM25 是否返回空）
    assert all("A专有" not in r["content"] for r in res_b)
    res_a = await rag_store.retrieve_chunks(pool, "内容", k=5, workspace_id="wsA")
    assert all("B专有" not in r["content"] for r in res_a)


async def test_rag_default_space_isolated(patch_embed):
    pool = _FakePool()
    from agent_server.rag.chunker import Chunk

    await rag_store.add_document(pool, "s.txt", [Chunk(text="默认空间内容", heading="h")])
    res = await rag_store.retrieve_chunks(pool, "内容", k=5, workspace_id="other")
    assert all("默认空间" not in r["content"] for r in res)


async def test_memory_insert_carries_workspace_id(patch_embed):
    pool = _FakePool()
    await mb.remember_fact(pool, "wsA", "用户A是财务", "semantic", 0.9)
    inserts = _calls_with(pool, "INSERT INTO memories")
    assert inserts, "remember_fact 应执行 INSERT INTO memories"
    assert inserts[-1][0] == "wsA"  # user_id 列承载 workspace_id


async def test_memory_recall_scoped_to_workspace(patch_embed):
    pool = _FakePool()
    await mb.remember_fact(pool, "wsA", "事实A", "semantic", 0.9)
    pool.calls.clear()  # 清掉写入记录，只看召回查询
    await mb.recall_typed(pool, "wsA", "任意", k=3)
    # 优化 G 决策：长期记忆复用 memories 表的 user_id 列承载 workspace_id
    where_ws = [p for sql, p in pool.calls if "user_id" in sql]
    assert where_ws, "recall SQL 应含 user_id（承载 workspace_id）WHERE"
    assert all("wsA" in p for p in where_ws)


async def test_memory_no_cross_contamination(patch_embed):
    pool = _FakePool()
    await mb.remember_fact(pool, "wsA", "用户A是财务", "semantic", 0.9)
    await mb.remember_fact(pool, "wsB", "用户B是工程师", "semantic", 0.9)
    res_b = await mb.recall_typed(pool, "wsB", "职业", k=3)
    assert all("财务" not in r for r in res_b)
    res_a = await mb.recall_typed(pool, "wsA", "职业", k=3)
    assert all("工程师" not in r for r in res_a)


async def test_memory_default_space_isolated(patch_embed):
    pool = _FakePool()
    await mb.remember_fact(pool, "default", "默认空间事实", "semantic", 0.8)
    res = await mb.recall_typed(pool, "custom", "事实", k=3)
    assert all("默认空间" not in r for r in res)
