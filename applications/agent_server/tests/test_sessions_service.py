"""多会话目录 service 单测（无 PG：fake pool 校验 SQL 形状/参数 + 纯函数派生）。

覆盖守门判据：
- session_id 形态快筛（uuid4 hex / 拒绝旧 thread 形态）；
- 会话 thread_id = 断言主体 base + 会话后缀；
- 归属不匹配 / 不存在 → resolve 返回 None（存量兼容，不切换 thread）；
- create/list/delete 参数含 org+user 归属、无 SQL 注入面。
"""

from __future__ import annotations

import asyncio

from agent_server.api import sessions_service as svc


class _Cursor:
    def __init__(self, row=None, rows=None, rowcount=1):
        self._row, self._rows, self.rowcount = row, rows or [], rowcount

    async def fetchone(self):
        return self._row

    async def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, pool):
        self._pool = pool

    async def execute(self, sql, params=None):
        self._pool.history.append((" ".join(sql.split()), tuple(params or ())))
        return self._pool.cursor


class _Pool:
    def __init__(self, cursor=None):
        self.history: list[tuple[str, tuple]] = []
        self.cursor = cursor or _Cursor()

    def connection(self):
        p = self

        class _Ctx:
            async def __aenter__(self):
                return _Conn(p)

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


_SESSION_ROW = (
    "s1", "acme", "alice", "tenant-acme--user-alice--session-s1", "会话1", "default", "default",
    "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
)


def test_new_session_id_is_uuid_hex():
    sid = svc.new_session_id()
    assert svc.is_session_id(sid)
    assert len(sid) == 32


def test_is_session_id_rejects_legacy_and_garbage():
    assert not svc.is_session_id(None)
    assert not svc.is_session_id("tenant-acme--user-alice")  # 旧 thread 形态
    assert not svc.is_session_id("x" * 32)  # 非 hex
    assert not svc.is_session_id("ABCDEF0123456789ABCDEF0123456789")  # 大写非 hex


def test_session_thread_id_appends_suffix():
    assert svc.session_thread_id("tenant-acme--user-alice", "abc") == (
        "tenant-acme--user-alice--session-abc"
    )


def test_resolve_session_thread_no_pool_or_bad_shape():
    assert asyncio.run(svc.resolve_session_thread(None, "a" * 32, org_id="acme", user_id="alice")) is None
    assert asyncio.run(svc.resolve_session_thread(_Pool(), "legacy", org_id="acme", user_id="alice")) is None


def test_get_session_filters_org_and_user():
    pool = _Pool(cursor=_Cursor(row=_SESSION_ROW))
    row = asyncio.run(svc.get_session(pool, "s1", org_id="acme", user_id="alice"))
    assert row is not None and row["session_id"] == "s1"
    sql, params = pool.history[-1]
    assert " org_id=%s" in sql and " user_id=%s" in sql
    assert params == ("s1", "acme", "alice")


def test_create_session_binds_org_user_and_derived_thread():
    pool = _Pool(cursor=_Cursor(row=_SESSION_ROW))
    row = asyncio.run(svc.create_session(
        pool, org_id="acme", user_id="alice",
        base_thread_id="tenant-acme--user-alice", title="新会话", workspace_id="w1",
    ))
    assert row["session_id"] == "s1"
    sql, params = pool.history[-1]
    assert sql.startswith("INSERT INTO agent_sessions")
    assert params[1] == "acme" and params[2] == "alice"  # org / user 归属
    assert params[3].startswith("tenant-acme--user-alice--session-")  # 派生 thread


def test_delete_session_requires_ownership():
    pool = _Pool(cursor=_Cursor(rowcount=0))
    deleted = asyncio.run(svc.delete_session(pool, "s1", org_id="acme", user_id="intruder"))
    assert deleted is False
    sql, params = pool.history[-1]
    assert sql.startswith("DELETE FROM agent_sessions")
    assert params == ("s1", "acme", "intruder")


def _session_row(title_source="default"):
    return (
        "s1", "acme", "alice", "tenant-acme--user-alice--session-s1", "旧标题",
        title_source, "default", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
    )


def test_set_title_manual_has_no_cas_and_marks_source():
    pool = _Pool(cursor=_Cursor(rowcount=1))
    ok = asyncio.run(svc.set_session_title(
        pool, "s1", "我改的名字", org_id="acme", user_id="alice",
        source=svc.TITLE_SOURCE_MANUAL,
    ))
    assert ok is True
    sql, params = pool.history[-1]
    assert "title_source=%s" in sql and "title_source" not in sql.split("WHERE")[1].split("SET")[0]
    assert "AND title_source" not in sql  # 手动改不带 CAS
    assert params == ("我改的名字", svc.TITLE_SOURCE_MANUAL, "s1", "acme", "alice")


def test_set_title_auto_uses_cas_on_default():
    pool = _Pool(cursor=_Cursor(rowcount=1))
    ok = asyncio.run(svc.set_session_title(
        pool, "s1", "自动标题", org_id="acme", user_id="alice",
        source=svc.TITLE_SOURCE_AUTO, expected_source=svc.TITLE_SOURCE_DEFAULT,
    ))
    assert ok is True
    sql, params = pool.history[-1]
    assert "AND title_source=%s" in sql
    assert params == ("自动标题", svc.TITLE_SOURCE_AUTO, "s1", "acme", "alice", svc.TITLE_SOURCE_DEFAULT)


def test_maybe_auto_title_skips_non_default_source():
    for src in (svc.TITLE_SOURCE_AUTO, svc.TITLE_SOURCE_MANUAL):
        pool = _Pool(cursor=_Cursor(row=_session_row(src)))
        result = asyncio.run(svc.maybe_auto_title(
            pool, "s1", org_id="acme", user_id="alice",
            question="查数据", answer="答案", llm=None,
        ))
        assert result is None
        assert all(not sql.startswith(("UPDATE", "INSERT")) for sql, _ in pool.history)  # 只读判定，无写操作


def test_maybe_auto_title_generates_and_cas_writes():
    pool = _Pool(cursor=_Cursor(row=_session_row(svc.TITLE_SOURCE_DEFAULT), rowcount=1))
    result = asyncio.run(svc.maybe_auto_title(
        pool, "s1", org_id="acme", user_id="alice",
        question="如何查询展会收藏量", answer="按 tenant_id 过滤统计", llm=None,
    ))
    assert result == "如何查询展会收藏量"  # LLM None → 回退截断问题
    sql, params = pool.history[-1]
    assert sql.startswith("UPDATE agent_sessions SET title=%s")
    assert "AND title_source=%s" in sql
    assert params[1] == svc.TITLE_SOURCE_AUTO
    assert params[-1] == svc.TITLE_SOURCE_DEFAULT


def test_maybe_auto_title_no_pool_or_missing_session():
    assert asyncio.run(svc.maybe_auto_title(
        None, "s1", org_id="acme", user_id="alice", question="q", answer="a", llm=None,
    )) is None
    pool = _Pool(cursor=_Cursor(row=None))
    assert asyncio.run(svc.maybe_auto_title(
        pool, "s1", org_id="acme", user_id="alice", question="q", answer="a", llm=None,
    )) is None
