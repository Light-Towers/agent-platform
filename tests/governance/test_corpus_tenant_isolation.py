"""隔离域加固行为测试（plan T9/T10，W1/W2）——不连真实 PG，fake psycopg 池可 CI。

覆盖点（越权回归，ADR-0006 D1/D4）：
- chunks / sql_* 读写谓词成对带 ``tenant_id``（workspace 归属不再单独承担隔离）；
- tenant 漏传 fail-fast（复用 _tenant_gate 哨兵），绝不静默落 default 共享桶；
- fetch_context 消除「空 workspace = 全库召回」旁路（tenant 谓词必经）；
- workspaces 归属表：同 id 跨租户互不越权（register 命名空间化 + assert 拦截）。

与既有 tests/governance/test_workspace_isolation.py（优化 G，workspace 单维）互补：
本文件验证在其之上补齐的 tenant 安全边界。
"""

from __future__ import annotations

import pytest
from agent_core.memory._tenant_gate import _TENANT_UNSET  # noqa: F401  供哨兵判定引用


class _Recorder:
    """记录所有 (sql, params) 调用的最小 fake 池；SELECT 走回调以支持行为断言。"""

    def __init__(self, select_handler=None):
        self.calls: list[tuple[str, tuple]] = []
        self._select_handler = select_handler

    def connection(self):
        return _ConnCtx(self)

    def run_select(self, sql, params):
        if self._select_handler is None:
            return []
        return self._select_handler(sql, params)


class _Cur:
    def __init__(self, recorder, sql, params):
        self._recorder = recorder
        self._sql = sql
        self._params = params or ()
        self._rows = None
        self.rowcount = 0

    async def fetchone(self):
        rows = await self.fetchall()
        return rows[0] if rows else None

    async def fetchall(self):
        if self._rows is None:
            self._rows = self._recorder.run_select(self._sql, self._params)
        return self._rows


class _Conn:
    def __init__(self, recorder):
        self._recorder = recorder

    def cursor(self):
        return self

    async def execute(self, sql, params=None):
        self._recorder.calls.append((sql, tuple(params or ())))
        return _Cur(self._recorder, sql, params)

    async def executemany(self, sql, params_list):
        for p in params_list:
            self._recorder.calls.append((sql, tuple(p)))


class _ConnCtx:
    def __init__(self, recorder):
        self._recorder = recorder

    async def __aenter__(self):
        return _Conn(self._recorder)

    async def __aexit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def _stub_embed(monkeypatch):
    async def _texts(texts, dim=512):
        return [[0.0] * dim for _ in texts]

    async def _query(text, dim=512):
        return [0.0] * dim

    monkeypatch.setattr("agent_server.rag.embed.embed_texts", _texts)
    monkeypatch.setattr("agent_server.rag.embed.embed_query", _query)


def _chunks_select_for(data):
    """按 (tenant, workspace) 过滤内存 chunks 的 select handler（模拟真实谓词效果）。

    覆盖 store 发出的三种 chunks 查询形态：COUNT 签名、BM25 语料加载、
    最终按 id 集回取（tenant + id = ANY + workspace 三重谓词）。
    """

    def _match(r, tenant, ws):
        return r["tenant_id"] == tenant and r["workspace_id"] == ws

    def _handler(sql, params):
        if "FROM chunks" not in sql:
            return []
        if "COUNT" in sql:
            tenant, ws = params[0], params[1]
            rows = [r for r in data if _match(r, tenant, ws)]
            return [(len(rows), max([r["id"] for r in rows], default=0))]
        if "id = ANY" in sql:
            tenant, ids, ws = params[0], set(params[1]), params[2]
            return [
                (r["id"], r["source"], r["heading"], r["content"])
                for r in data if r["id"] in ids and _match(r, tenant, ws)
            ]
        if "SELECT id, content" in sql:
            tenant, ws = params[0], params[1]
            return [(r["id"], r["content"]) for r in data if _match(r, tenant, ws)]
        return []

    return _handler


async def test_add_document_requires_explicit_tenant():
    """漏传 tenant → fail-fast（不落共享 default 桶）。"""
    from agent_server.rag.chunker import Chunk
    from agent_server.rag.store import add_document

    rec = _Recorder()
    with pytest.raises(ValueError, match="显式传入"):
        await add_document(rec, "a.md", [Chunk(text="x", heading="h")], workspace_id="wsA")


async def test_chunks_write_pairs_tenant_and_workspace():
    from agent_server.rag.chunker import Chunk
    from agent_server.rag.store import add_document

    rec = _Recorder()
    await add_document(rec, "a.md", [Chunk(text="内容", heading="h")], workspace_id="wsA", tenant_id="tenantA")
    inserts = [p for sql, p in rec.calls if "INSERT INTO chunks" in sql]
    assert inserts
    # 列序 (tenant_id, doc_id, source, heading, content, embedding, workspace_id)
    assert inserts[-1][0] == "tenantA"
    assert inserts[-1][-1] == "wsA"


async def test_retrieve_chunks_isolates_across_tenants():
    """核心越权回归：tenantA 导入的 chunk，tenantB 检索不到（跨租户不可见）。"""
    import agent_server.rag.store as _s
    from agent_server.rag import store as rag_store

    data = [
        {"id": 1, "tenant_id": "tenantA", "workspace_id": "wsX", "content": "A专有", "source": "a", "heading": ""},
        {"id": 2, "tenant_id": "tenantB", "workspace_id": "wsX", "content": "B专有", "source": "b", "heading": ""},
    ]

    async def _fake_vs(pool, table, cols, emb, k=1, where="", where_params=()):
        assert "tenant_id" in where, f"chunks 向量召回必须带 tenant 谓词: {where}"
        assert "workspace_id" in where, f"chunks 向量召回必须带 workspace 谓词: {where}"
        tenant, ws = where_params[0], where_params[1]
        return [(r["id"], 0.1) for r in data if r["tenant_id"] == tenant and r["workspace_id"] == ws]

    orig_vs = _s.vector_search
    _s.vector_search = _fake_vs
    try:
        rec_b = _Recorder(_chunks_select_for(data))
        res_b = await rag_store.retrieve_chunks(rec_b, "专有", k=5, workspace_id="wsX", tenant_id="tenantB")
        contents = [r["content"] for r in res_b]
        assert all("A专有" not in c for c in contents), "跨租户泄漏：B 读到了 A 的 chunk"
        assert any("B专有" in c for c in contents), "本租户数据应可召回"
    finally:
        _s.vector_search = orig_vs


async def test_sql_fetch_context_always_scoped_by_tenant():
    """fetch_context 消除空 workspace 全库旁路：tenant 谓词必经。"""
    import agent_server.sql.schema_store as _ss
    from agent_server.sql.schema_store import fetch_context

    captured: list[tuple[str, tuple]] = []

    async def _fake_vs(pool, table, cols, emb, k=1, where="", where_params=()):
        captured.append((where, tuple(where_params or ())))
        return []

    orig = _ss.vector_search
    _ss.vector_search = _fake_vs
    try:
        rec = _Recorder()
        # 空 workspace：仍必须带 tenant 谓词（旧实现此处完全不过滤）
        await fetch_context(rec, "问题", workspace_id="", tenant_id="tenantA")
        assert captured, "fetch_context 应发起向量检索"
        for where, params in captured:
            assert "tenant_id" in where, f"sql_* 召回缺 tenant 谓词（全库旁路）: {where}"
            assert "tenantA" in params
    finally:
        _ss.vector_search = orig


async def test_sql_store_insert_requires_tenant():
    from agent_server.sql.schema_store import store_ddl

    rec = _Recorder()
    with pytest.raises(ValueError, match="显式传入"):
        await store_ddl(rec, "CREATE TABLE t(a int)", workspace_id="ws")


async def test_sql_store_insert_carries_tenant():
    from agent_server.sql.schema_store import store_example

    rec = _Recorder()
    await store_example(rec, "Q", "SELECT 1", workspace_id="wsA", tenant_id="tenantA")
    inserts = [p for sql, p in rec.calls if "INSERT INTO sql_examples" in sql]
    assert inserts and inserts[-1][0] == "tenantA", "列序首位应为 tenant_id"


# --- workspaces 归属表（T10 / D4 方案 A） -----------------------------------

async def test_workspace_registration_is_namespaced_per_tenant():
    """同 id 由两租户各自注册 → 两行互不冲突（复合 PK 命名空间化）。"""
    from agent_runtime.workspace_registry import register_workspace

    rows: dict[tuple, dict] = {}

    def _handler(sql, params):
        if "SELECT 1 FROM workspaces" in sql:
            return [1] if (params[0], params[1]) in rows else []
        return []

    class _WConn(_Conn):
        async def execute(self, sql, params=None):
            self._recorder.calls.append((sql, tuple(params or ())))
            if "INSERT INTO workspaces" in sql:
                rows[(params[0], params[1])] = {"tenant_id": params[0], "id": params[1]}
            return _Cur(self._recorder, sql, params)

    class _WCtx(_ConnCtx):
        async def __aenter__(self):
            return _WConn(self._recorder)

    rec = _Recorder(_handler)
    rec.connection = lambda: _WCtx(rec)

    await register_workspace(rec, "shared-ws", "tenantA")
    await register_workspace(rec, "shared-ws", "tenantB")
    assert ("tenantA", "shared-ws") in rows and ("tenantB", "shared-ws") in rows


def _make_ws_store():
    """构造一个拦截 workspaces SELECT/INSERT 的 fake 池，返回 (recorder, rows)。"""
    rows: dict[tuple, dict] = {}

    def _handler(sql, params):
        if "SELECT 1 FROM workspaces" in sql:
            return [1] if (params[0], params[1]) in rows else []
        return []

    class _WConn(_Conn):
        async def execute(self, sql, params=None):
            self._recorder.calls.append((sql, tuple(params or ())))
            if "INSERT INTO workspaces" in sql:
                rows[(params[0], params[1])] = {"tenant_id": params[0], "id": params[1]}
            return _Cur(self._recorder, sql, params)

    class _WCtx(_ConnCtx):
        async def __aenter__(self):
            return _WConn(self._recorder)

    rec = _Recorder(_handler)
    rec.connection = lambda: _WCtx(rec)
    return rec, rows


async def test_resolve_workspace_returns_true_and_registers():
    """resolve_workspace：首次自动注册并返回 True；再次调用幂等不新增行。"""
    from agent_runtime.workspace_registry import resolve_workspace

    rec, rows = _make_ws_store()
    assert await resolve_workspace(rec, "tenantA", "shared-ws") is True
    assert ("tenantA", "shared-ws") in rows
    assert await resolve_workspace(rec, "tenantA", "shared-ws") is True
    assert len(rows) == 1, "幂等：不应重复插入"


async def test_resolve_workspace_namespaces_same_id_across_tenants():
    """同 workspace_id 由两租户各自 resolve → 两行分属两租户（禁止共享行，plan §4 T10）。"""
    from agent_runtime.workspace_registry import resolve_workspace

    rec, rows = _make_ws_store()
    await resolve_workspace(rec, "tenantA", "team-x")
    await resolve_workspace(rec, "tenantB", "team-x")
    assert ("tenantA", "team-x") in rows and ("tenantB", "team-x") in rows
    assert len(rows) == 2


async def test_resolve_workspace_rejects_blank_inputs():
    """空 tenant / 空 workspace_id → fail-fast（不静默落错命名空间）。"""
    from agent_runtime.workspace_registry import resolve_workspace

    with pytest.raises(ValueError):
        await resolve_workspace(None, "", "ws")
    with pytest.raises(ValueError):
        await resolve_workspace(None, "tenantA", "   ")


async def test_assert_workspace_access_blocks_foreign_tenant():
    """workspace 仅归属 tenantA 时，tenantB 显式越权引用 → WorkspaceTenantMismatch。"""
    from agent_runtime.workspace_registry import WorkspaceTenantMismatch, assert_workspace_access

    def _handler(sql, params):
        if "SELECT tenant_id FROM workspaces" in sql:
            return [("tenantA",)]  # 该 id 已被 tenantA 认领
        return []

    rec = _Recorder(_handler)
    with pytest.raises(WorkspaceTenantMismatch):
        await assert_workspace_access(rec, "victim-ws", "tenantB")


async def test_assert_workspace_access_allows_owner_and_unknown():
    from agent_runtime.workspace_registry import assert_workspace_access

    owner = _Recorder(lambda sql, p: [("tenantA",)])
    await assert_workspace_access(owner, "ws", "tenantA")  # 属主放行

    unknown = _Recorder(lambda sql, p: [])  # 未注册 → 放行（读结果已被 tenant 谓词约束）
    await assert_workspace_access(unknown, "ws", "tenantA")


async def test_server_tenant_id_fails_fast_without_context():
    """未绑定 ContextVar 且未给显式 default → fail-fast（不给隐式缺省）。"""
    from agent_runtime.workspace_registry import server_tenant_id

    with pytest.raises(ValueError, match="显式传入"):
        server_tenant_id()
    # 显式部署级 default 可用（单租户）
    assert server_tenant_id("default") == "default"
