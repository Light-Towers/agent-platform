"""行为级租户隔离回归（C-1 修复，2026-09-25）：真实 PostgreSQL 上验证 legacy 边界。

背景：v5 迁移把多租户上线前历史语料全量归并进 ``tenant_id='default'`` 桶，
7e442c4 将召回读谓词从过渡期 ``ANY(%s)`` 收紧为精确 ``tenant_id = %s``。
本文件补上此前全仓缺失的**行为级**覆盖（治理测试此前只断言 SQL 字符串形状，
fake 还兼容旧泄漏契约）：

1. 写入 legacy ``default`` 桶记忆 → 以真实租户 ``tenant-a`` 召回 → **断言读不到**
   （跨租户泄漏回归，若读谓词退回作用域列表此用例必红）；
2. ``default`` 租户自身仍可读到 legacy 行（数据未丢，只是收窄作用域）；
3. tenant-a 与 tenant-b 在同 workspace 下互不可见（正向隔离）。

挂 ``requires_pg``：归属 agent-platform-ha workflow（真实 PG 门禁）。
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.requires_pg

_DIM = 512  # CI 环境 embedder 为 Mock（dim=512），与 memories.embedding 列维度一致
_EMBEDDING = [0.1] * _DIM


def _iso_user() -> str:
    """隔离的 workspace（user_id）标识，避免污染/命中其他测试数据。"""
    return f"ws-tenant-iso-{uuid.uuid4().hex[:8]}"


@pytest.fixture()
async def seeded_memories(pg_pool):
    """写入三条记忆：legacy default 桶 1 条 + tenant-a/tenant-b 各 1 条（同 workspace）。

    清理置于 try/finally：即使断言失败也按隔离 user_id 精确删除造数。
    """
    ws = _iso_user()
    rows = [
        ("default", ws, "LEGACY-DEFAULT-SECRET-历史记忆", "semantic", 0.9),
        ("tenant-a", ws, "TENANT-A-PRIVATE-事实", "semantic", 0.9),
        ("tenant-b", ws, "TENANT-B-PRIVATE-事实", "semantic", 0.9),
    ]
    async with pg_pool.connection() as conn:
        for tenant, user_id, content, mtype, importance in rows:
            await conn.execute(
                "INSERT INTO memories (tenant_id, user_id, content, memory_type, "
                "importance, embedding) VALUES (%s, %s, %s, %s, %s, %s)",
                (tenant, user_id, content, mtype, importance, _EMBEDDING),
            )
    try:
        yield {"ws": ws, "contents": [r[2] for r in rows]}
    finally:
        async with pg_pool.connection() as conn:
            await conn.execute("DELETE FROM memories WHERE user_id = %s", (ws,))


async def test_legacy_default_bucket_not_readable_by_real_tenant(pg_pool, seeded_memories):
    """核心回归：真实租户召回**绝不含** legacy default 桶内容。"""
    from agent_core.memory.typed import recall_typed

    ws = seeded_memories["ws"]
    memories = await recall_typed(
        pg_pool, ws, "历史记忆", k=10, embedding=_EMBEDDING, tenant_id="tenant-a"
    )
    contents = [m.content for m in memories]
    assert "TENANT-A-PRIVATE-事实" in contents, "本租户记忆应可召回"
    assert "LEGACY-DEFAULT-SECRET-历史记忆" not in contents, (
        "legacy default 桶记忆对真实租户不可见（读谓词若退回 ANY 作用域列表此断言必红）"
    )


async def test_default_tenant_still_reads_legacy_bucket(pg_pool, seeded_memories):
    """default 租户自身仍可读 legacy 行——收窄作用域 ≠ 数据丢失。"""
    from agent_core.memory.typed import recall_typed

    ws = seeded_memories["ws"]
    memories = await recall_typed(
        pg_pool, ws, "历史记忆", k=10, embedding=_EMBEDDING, tenant_id="default"
    )
    assert any("LEGACY-DEFAULT-SECRET-历史记忆" in m.content for m in memories)


async def test_cross_tenant_same_workspace_isolated_real_pg(pg_pool, seeded_memories):
    """正向隔离：tenant-a 与 tenant-b 同 workspace 下互不可见（真实 PG 行为级）。"""
    from agent_core.memory.typed import recall_typed

    ws = seeded_memories["ws"]
    mem_a = await recall_typed(
        pg_pool, ws, "事实", k=10, embedding=_EMBEDDING, tenant_id="tenant-a"
    )
    mem_b = await recall_typed(
        pg_pool, ws, "事实", k=10, embedding=_EMBEDDING, tenant_id="tenant-b"
    )
    contents_a = [m.content for m in mem_a]
    contents_b = [m.content for m in mem_b]
    assert "TENANT-B-PRIVATE-事实" not in contents_a
    assert "TENANT-A-PRIVATE-事实" not in contents_b


# --- ADR-0006 隔离域加固（plan T9/T10/T13）：真实 PG 行为级回归 ----------------


async def test_memories_dual_scope_real_pg(pg_pool, monkeypatch):
    """双 scope 真实 PG 回归（migration 008 + _to_pg_vector 向量算子端到端）。

    验证新增的 remember_typed_scoped / recall_user_profile 在真实 PG 上跨空间生效：
    wsA 写的 user 画像在 wsB 经 user 路可召回，wsA 的 workspace 项目事实不串入 wsB。
    两路融合（按 score 降序）与门面 memory_backend.recall_typed 同构。
    """
    from agent_core.memory import typed as T

    monkeypatch.setattr(T, "memory_dual_scope_enabled", lambda: True)
    tenant = f"t-ds-{uuid.uuid4().hex[:8]}"
    user = f"alice-{uuid.uuid4().hex[:8]}"
    ws_a, ws_b = f"wsa-{uuid.uuid4().hex[:8]}", f"wsb-{uuid.uuid4().hex[:8]}"
    try:
        await T.remember_typed_scoped(
            pg_pool, tenant, user, ws_a, "user", "DUAL-USER-偏好上海", embedding=_EMBEDDING,
        )
        await T.remember_typed_scoped(
            pg_pool, tenant, ws_a, ws_a, "workspace", "DUAL-WS-项目Postgres", embedding=_EMBEDDING,
        )
        # wsB 提问：workspace 路查 wsB（空）+ user 路查 alice（画像命中），门面式融合
        ws_rows = await T.recall_typed(
            pg_pool, user_id=ws_b, question="去哪玩", embedding=_EMBEDDING, tenant_id=tenant,
        )
        prof_rows = await T.recall_user_profile(
            pg_pool, tenant_id=tenant, user_id=user, question="去哪玩", embedding=_EMBEDDING,
        )
        contents = [m.content for m in sorted(
            list(ws_rows) + list(prof_rows), key=lambda m: m.score, reverse=True
        )]
        assert "DUAL-USER-偏好上海" in contents, "user 画像应跨 workspace 召回（真实 PG）"
        assert "DUAL-WS-项目Postgres" not in contents, "wsA 项目事实不得串入 wsB"
    finally:
        async with pg_pool.connection() as conn:
            await conn.execute("DELETE FROM memories WHERE tenant_id = %s", (tenant,))


async def test_workspaces_ownership_cross_tenant_real_pg(pg_pool):
    """workspaces 归属表真实 PG 回归（migration 007，D4 方案 A）。

    同 id 由 tenantA 注册后，tenantB 显式越权引用 → WorkspaceTenantMismatch；
    tenantB 自行注册（复合 PK 命名空间化）后成为属主 → 放行。两行分属两租户。
    """
    from agent_runtime import workspace_registry as wr

    ws = f"shared-{uuid.uuid4().hex[:8]}"
    t_a, t_b = f"owna-{uuid.uuid4().hex[:8]}", f"ownb-{uuid.uuid4().hex[:8]}"
    try:
        await wr.register_workspace(pg_pool, ws, t_a)
        await wr.assert_workspace_access(pg_pool, ws, t_a)  # 属主放行
        with pytest.raises(wr.WorkspaceTenantMismatch):
            await wr.assert_workspace_access(pg_pool, ws, t_b)  # 越权拦截
        await wr.register_workspace(pg_pool, ws, t_b)  # 命名空间化：同 id 各自一行
        await wr.assert_workspace_access(pg_pool, ws, t_b)
        async with pg_pool.connection() as conn:
            cur = await conn.execute(
                "SELECT count(DISTINCT tenant_id) FROM workspaces WHERE id = %s", (ws,)
            )
            row = await cur.fetchone()
        assert row[0] == 2, "同 id 应存在两租户各自的归属行"
    finally:
        async with pg_pool.connection() as conn:
            await conn.execute("DELETE FROM workspaces WHERE id = %s", (ws,))


async def test_chunks_tenant_predicate_isolates_real_pg(pg_pool):
    """chunks 补 tenant_id 后真实 PG 谓词隔离（migration 006，embedding 置 NULL）。

    同 workspace_id、不同租户写入 → 按 (tenant_id, workspace_id) 成对谓词只命中本租户，
    跨租户返回空（不再靠客户端可传的 workspace_id 单独隔离）。embedding 列置 NULL
    避开向量适配，专注验证列存在 + 租户谓词生效。
    """
    tenant_a, tenant_b = f"ca-{uuid.uuid4().hex[:8]}", f"cb-{uuid.uuid4().hex[:8]}"
    ws = f"ws-shared-{uuid.uuid4().hex[:8]}"
    async with pg_pool.connection() as conn:
        for t in (tenant_a, tenant_b):
            await conn.execute(
                "INSERT INTO chunks (tenant_id, doc_id, source, heading, content, embedding, workspace_id) "
                "VALUES (%s, %s, %s, %s, %s, NULL, %s)",
                (t, f"doc-{t}", "s", "h", f"CORPUS-{t}", ws),
            )
    try:
        async with pg_pool.connection() as conn:
            cur = await conn.execute(
                "SELECT content FROM chunks WHERE tenant_id = %s AND workspace_id = %s",
                (tenant_a, ws),
            )
            rows = [r[0] for r in await cur.fetchall()]
        assert rows == [f"CORPUS-{tenant_a}"], "跨租户 chunk 不可见（tenant 边界生效）"
    finally:
        async with pg_pool.connection() as conn:
            await conn.execute(
                "DELETE FROM chunks WHERE tenant_id = ANY(%s) AND workspace_id = %s",
                ([tenant_a, tenant_b], ws),
            )


async def test_sql_corpus_tenant_predicate_isolates_real_pg(pg_pool):
    """sql_ddl / sql_docs / sql_examples 补 tenant_id 后真实 PG 谓词隔离（migration 006）。

    与 chunks 同一形态：同 workspace_id、不同租户写入语料（embedding 置 NULL），
    按 (tenant_id, workspace_id) 成对谓词只命中本租户，tenantB 查召回为空。
    覆盖 plan T9 “tenantA 导入 SQL 语料 → tenantB 召回为空”验收。
    """
    tenant_a, tenant_b = f"sa-{uuid.uuid4().hex[:8]}", f"sb-{uuid.uuid4().hex[:8]}"
    ws = f"ws-sql-{uuid.uuid4().hex[:8]}"
    specs = {
        "sql_ddl": ("content", "DDL-{t}"),
        "sql_docs": ("content", "DOC-{t}"),
        "sql_examples": ("question", "Q-{t}"),
    }
    try:
        async with pg_pool.connection() as conn:
            for table, (col, tmpl) in specs.items():
                for t in (tenant_a, tenant_b):
                    if table == "sql_examples":
                        await conn.execute(
                            "INSERT INTO sql_examples (tenant_id, question, sql, embedding, workspace_id) "
                            "VALUES (%s, %s, %s, NULL, %s)",
                            (t, tmpl.format(t=t), "SELECT 1", ws),
                        )
                    else:
                        await conn.execute(
                            "INSERT INTO {tbl} (tenant_id, content, embedding, workspace_id) "
                            "VALUES (%s, %s, NULL, %s)".format(tbl=table),
                            (t, tmpl.format(t=t), ws),
                        )
        async with pg_pool.connection() as conn:
            for table, (col, _tmpl) in specs.items():
                cur = await conn.execute(
                    "SELECT {col} FROM {tbl} WHERE tenant_id = %s AND workspace_id = %s".format(
                        col=col, tbl=table
                    ),
                    (tenant_a, ws),
                )
                vals = [r[0] for r in await cur.fetchall()]
                assert any(v.endswith(tenant_a) for v in vals), f"{table} 本租户语料应可查"
                assert all(tenant_b not in v for v in vals), f"{table} 跨租户语料不可见（tenant 边界生效）"
    finally:
        async with pg_pool.connection() as conn:
            for table in specs:
                await conn.execute(
                    "DELETE FROM {tbl} WHERE tenant_id = ANY(%s) AND workspace_id = %s".format(tbl=table),
                    ([tenant_a, tenant_b], ws),
                )


async def test_episodic_tenant_isolation_real_pg(pg_pool):
    """episodic_memories 补 tenant_id 后真实 PG 隔离（plan T1 / migration 010）。

    tenantA 写 Episode → tenantB recall/list_all 为空；get 跨租户为空。
    """
    from agent_runtime.episodic_memory import Episode, EpisodeOutcome
    from agent_runtime.memory_pg import PgEpisodicStore

    store = PgEpisodicStore(pg_pool)
    t_a, t_b = f"ep-{uuid.uuid4().hex[:8]}", f"ep-{uuid.uuid4().hex[:8]}"
    eid = f"epi-{uuid.uuid4().hex[:8]}"
    try:
        await store.save(
            Episode(episode_id=eid, execution_id="exec-1", task_summary="EPISODIC-PRIVATE-A",
                     outcome=EpisodeOutcome.SUCCESS, importance=0.9),
            tenant_id=t_a,
        )
        assert len(await store.recall("EPISODIC-PRIVATE", tenant_id=t_a)) == 1
        assert await store.recall("EPISODIC-PRIVATE", tenant_id=t_b) == [], "跨租户 recall 不可见"
        assert await store.get(eid, tenant_id=t_b) is None, "跨租户 get 不可见"
        assert all(e.episode_id != eid for e in await store.list_all(tenant_id=t_b))
    finally:
        async with pg_pool.connection() as conn:
            await conn.execute(
                "DELETE FROM episodic_memories WHERE tenant_id = ANY(%s)", ([t_a, t_b],)
            )


async def test_procedural_tenant_namespaced_real_pg(pg_pool):
    """procedural_memories PK 命名空间化 (tenant_id, name, version) 真实 PG 回归（plan T1）。

    同 (name, version) 由两租户各存一行、互不可见（技能源于租户轨迹，跨租户隔离）。
    """
    from agent_runtime.memory_pg import PgProceduralStore
    from agent_runtime.procedural_memory import ProceduralEntry

    store = PgProceduralStore(pg_pool)
    t_a, t_b = f"pr-{uuid.uuid4().hex[:8]}", f"pr-{uuid.uuid4().hex[:8]}"
    name = f"auto_shared_{uuid.uuid4().hex[:6]}"
    try:
        await store.save(ProceduralEntry(name=name, version="auto", kind="function", description="A", lifecycle="draft"), tenant_id=t_a)
        await store.save(ProceduralEntry(name=name, version="auto", kind="function", description="B", lifecycle="draft"), tenant_id=t_b)
        a = await store.load(name, "auto", tenant_id=t_a)
        b = await store.load(name, "auto", tenant_id=t_b)
        assert a is not None and a.description == "A"
        assert b is not None and b.description == "B", "同 (name,version) 跨租户各自一行（复合 PK 生效）"
        assert len(await store.list_all(tenant_id=t_a)) == 1
    finally:
        async with pg_pool.connection() as conn:
            await conn.execute(
                "DELETE FROM procedural_memories WHERE tenant_id = ANY(%s)", ([t_a, t_b],)
            )
