"""memories 双 scope 行为测试（plan T13，W3 / 用户拍板"画像层必须存在"）。

不连真实 PG：fake psycopg 池按内核 ``typed`` 实际发出的 SQL 形态在内存过滤，验证：
- 旧 5 个公开符号（remember_typed/recall_typed）签名不变、行为零变更（ADR-0004）；
- 新增 ``remember_typed_scoped`` / ``recall_user_profile``（双 scope 专用入口）：
  - 开关关：scoped 写降级为 6 列 workspace 行（user 画像不跨空间）；
  - 开关开：workspace 行落 user_id='default' 占位 + workspace_id=ws；user 行落真实 user_id；
- user 路（``recall_user_profile``）跨 workspace 命中，workspace 路不串项目事实；
- 两路融合（按 score 降序）与门面 ``memory_backend.recall_typed`` 同构（不改评分公式）。

内核不下沉 embedder，测试直接传 embedding 列表（_to_pg_vector 未装 pgvector 时
原样透传 list，内存 fake 不解释向量）。
"""

from __future__ import annotations

import pytest
from agent_core.memory import typed as T


class _MemFake:
    """内存 memories 表 + 按 SQL 形态路由的 fake 池。"""

    def __init__(self):
        self.rows: list[dict] = []
        self._seq = 0

    def connection(self):
        return _Ctx(self)


class _Cur:
    def __init__(self, store, sql, params):
        self._store = store
        self._sql = sql
        self._p = params or ()
        self.rowcount = 0

    async def fetchall(self):
        sql, p = self._sql, self._p
        if "FROM memories" not in sql:
            return []
        # 双列 workspace 路：WHERE tenant=%s AND scope=%s AND (workspace_id=%s OR user_id=%s) ...
        # 单列 user 路：WHERE tenant=%s AND scope=%s AND user_id=%s ...
        tenant, scope = p[0], p[1]
        if "workspace_id = %s OR user_id = %s" in sql:
            ws = p[2]
            matched = [
                r for r in self._store.rows
                if r["tenant_id"] == tenant and r["scope"] == scope
                and (r["workspace_id"] == ws or r["user_id"] == ws)
            ]
        else:
            uid = p[2]
            matched = [
                r for r in self._store.rows
                if r["tenant_id"] == tenant and r["scope"] == scope and r["user_id"] == uid
            ]
        return [(r["content"], r["memory_type"], r["importance"], None) for r in matched]

    async def fetchone(self):
        rows = await self.fetchall()
        return rows[0] if rows else None


class _Ctx:
    def __init__(self, store):
        self._store = store

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def cursor(self):
        return self

    async def execute(self, sql, params=None):
        p = params or ()
        s = sql.strip()
        cur = _Cur(self._store, sql, p)
        if s.startswith("INSERT INTO memories"):
            self._store._seq += 1
            if "workspace_id" in s and "scope" in s:
                # 8 列新布局：(tenant, user_id, workspace_id, scope, content, emb, type, imp)
                self._store.rows.append({
                    "id": self._store._seq, "tenant_id": p[0], "user_id": p[1],
                    "workspace_id": p[2], "scope": p[3], "content": p[4],
                    "memory_type": p[6], "importance": p[7],
                })
            else:
                # 6 列旧布局：(tenant, user_id, content, emb, type, imp)
                self._store.rows.append({
                    "id": self._store._seq, "tenant_id": p[0], "user_id": p[1],
                    "workspace_id": None, "scope": "workspace", "content": p[2],
                    "memory_type": p[4], "importance": p[5],
                })
        elif s.startswith("DELETE FROM memories"):
            before = len(self._store.rows)
            if "scope = %s" in s and "importance" in s:
                tenant, scope, ws = p[0], p[1], p[2]
                self._store.rows = [
                    r for r in self._store.rows
                    if not (r["tenant_id"] == tenant and r["scope"] == scope
                            and (r["workspace_id"] == ws or r["user_id"] == ws))
                ]
            else:
                tenant, ws, mid = p[0], p[1], p[3]
                self._store.rows = [
                    r for r in self._store.rows
                    if not (r["tenant_id"] == tenant
                            and (r["workspace_id"] == ws or r["user_id"] == ws)
                            and r["id"] == mid)
                ]
            cur.rowcount = before - len(self._store.rows)
        return cur


@pytest.fixture
def dual_on(monkeypatch):
    monkeypatch.setattr(T, "memory_dual_scope_enabled", lambda: True)
    return _MemFake()


@pytest.fixture
def dual_off(monkeypatch):
    monkeypatch.setattr(T, "memory_dual_scope_enabled", lambda: False)
    return _MemFake()


async def test_flag_off_writes_legacy_layout(dual_off):
    """开关关：workspace 行仍落 user_id 列（行为零变更，与旧实例读写兼容）。"""
    await T.remember_typed(
        dual_off, user_id="wsA", fact="偏好上海", embedding=[0.1], tenant_id="tenantA",
    )
    row = dual_off.rows[0]
    assert row["user_id"] == "wsA"
    assert row["workspace_id"] is None
    assert row["scope"] == "workspace"


async def test_flag_on_workspace_row_uses_placeholder(dual_on):
    """开关开：scope='workspace' 行落 user_id='default' 占位 + workspace_id=ws。"""
    await T.remember_typed_scoped(
        dual_on, "tenantA", "wsA", "wsA", "workspace", "项目用 Postgres", embedding=[0.1],
    )
    row = dual_on.rows[0]
    assert row["user_id"] == "default"
    assert row["workspace_id"] == "wsA"
    assert row["scope"] == "workspace"


async def test_flag_on_user_profile_row(dual_on):
    """开关开：scope='user' 行落真实 user_id（跨 workspace 画像）。"""
    await T.remember_typed_scoped(
        dual_on, "tenantA", "alice", "wsA", "user", "偏好上海", embedding=[0.1],
    )
    row = dual_on.rows[0]
    assert row["user_id"] == "alice"
    assert row["scope"] == "user"


async def test_flag_off_scoped_degrades_to_workspace(dual_off):
    """开关关：remember_typed_scoped 降级为 6 列 workspace 行（不写错位，画像不跨空间）。"""
    await T.remember_typed_scoped(
        dual_off, "tenantA", "alice", "wsA", "user", "偏好上海", embedding=[0.1],
    )
    row = dual_off.rows[0]
    assert row["user_id"] == "wsA"       # key = workspace_id
    assert row["workspace_id"] is None
    assert row["scope"] == "workspace"


def _fuse(*paths):
    """门面融合近似：多路 TypedMemory 按 score 降序合并（与 memory_backend.recall_typed 同构）。"""
    return sorted((m for p in paths for m in p), key=lambda m: m.score, reverse=True)


async def test_user_profile_recalled_across_workspaces(dual_on):
    """T13 验收：wsA 写的 user 画像，在 wsB 经 user 路可召回；wsA 项目事实不串入 wsB。"""
    await T.remember_typed_scoped(
        dual_on, "tenantA", "alice", "wsA", "user", "偏好上海", embedding=[0.1],
    )
    await T.remember_typed_scoped(
        dual_on, "tenantA", "wsA", "wsA", "workspace", "项目Q：Postgres 迁移", embedding=[0.1],
    )
    # wsB 提问：workspace 路查 wsB（无 wsA 项目事实），user 路查 alice（画像命中）
    ws = await T.recall_typed(dual_on, user_id="wsB", question="去哪玩", embedding=[0.1], tenant_id="tenantA")
    prof = await T.recall_user_profile(
        dual_on, tenant_id="tenantA", user_id="alice", question="去哪玩", embedding=[0.1],
    )
    contents = [m.content for m in _fuse(ws, prof)]
    assert "偏好上海" in contents, "user 画像应跨 workspace 召回"
    assert "项目Q：Postgres 迁移" not in contents, "wsA 的 workspace 事实不得串入 wsB"


async def test_workspace_facts_do_not_leak_without_profile(dual_on):
    """仅 workspace 路：跨 workspace 项目事实互不可见。"""
    await T.remember_typed_scoped(
        dual_on, "tenantA", "wsA", "wsA", "workspace", "A专有", embedding=[0.1],
    )
    await T.remember_typed_scoped(
        dual_on, "tenantA", "wsB", "wsB", "workspace", "B专有", embedding=[0.1],
    )
    res_a = await T.recall_typed(dual_on, user_id="wsA", question="专有", embedding=[0.1], tenant_id="tenantA")
    res_b = await T.recall_typed(dual_on, user_id="wsB", question="专有", embedding=[0.1], tenant_id="tenantA")
    assert [m.content for m in res_a] == ["A专有"]
    assert [m.content for m in res_b] == ["B专有"]


async def test_cross_tenant_user_profile_isolated(dual_on):
    """同名用户跨租户隔离：tenantB 召不到 tenantA 的 alice 画像。"""
    await T.remember_typed_scoped(
        dual_on, "tenantA", "alice", "wsA", "user", "A的画像", embedding=[0.1],
    )
    await T.remember_typed_scoped(
        dual_on, "tenantB", "alice", "wsB", "user", "B的画像", embedding=[0.1],
    )
    prof_a = await T.recall_user_profile(
        dual_on, tenant_id="tenantA", user_id="alice", question="画像", embedding=[0.1],
    )
    contents = [m.content for m in prof_a]
    assert "A的画像" in contents
    assert "B的画像" not in contents, "跨租户同名用户画像不得互见"


async def test_recall_user_profile_empty_when_flag_off(dual_off):
    """开关关时 user 画像降级为 workspace 行，user 路（scope='user'）召回为空。"""
    await T.remember_typed_scoped(
        dual_off, "tenantA", "alice", "wsA", "user", "偏好上海", embedding=[0.1],
    )
    prof = await T.recall_user_profile(
        dual_off, tenant_id="tenantA", user_id="alice", question="x", embedding=[0.1],
    )
    assert prof == []


async def test_consolidate_is_tenant_and_scope_scoped(dual_on):
    """巩固删除按 tenant + workspace 归属，绝不误删他租户/他空间行。"""
    await T.remember_typed_scoped(
        dual_on, "tenantA", "wsA", "wsA", "workspace", "A空间", importance=0.01, embedding=[0.1],
    )
    await T.remember_typed_scoped(
        dual_on, "tenantB", "wsB", "wsB", "workspace", "B空间", importance=0.01, embedding=[0.1],
    )
    deleted = await T.consolidate("wsA", dual_on, forget_threshold=0.5, age_days=0, tenant_id="tenantA")
    assert deleted == 1
    remaining = {r["content"] for r in dual_on.rows}
    assert "B空间" in remaining, "跨租户/跨空间行不受影响"
