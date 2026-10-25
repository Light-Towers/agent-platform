"""T3 归属接线测试：conversations 包装器 + workspace org 列 + trajectory 三列（plan §9.5/§9.6-5）。

无 PG 也能跑：fake pool 判 SQL 形状与参数序（与 nl2sql test_meta_knowledge_build 的
_FakePool 同思路）。requires_pg 级判据（真库并发双写等）待环境，见 plan §9.10。
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_runtime import conversations as conv
from agent_runtime.trajectory.models import TrajectoryRecord
from agent_runtime.trajectory.store_pg import PgTrajectoryStore
from agent_runtime.workspace_registry import register_workspace


class _FakeCursor:
    def __init__(self, row=None, rows=None, rowcount=0):
        self._row, self._rows, self.rowcount = row, rows or [], rowcount

    async def fetchone(self):
        return self._row

    async def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, pool):
        self._pool = pool

    async def execute(self, sql, params=None):
        self._pool.history.append((" ".join(sql.split()), tuple(params or ())))
        exc = self._pool.next_exc(sql)
        if exc:
            raise exc
        return self._pool.next_cursor(sql)


class _FakePool:
    """记录全部 SQL + 参数；按脚本化响应/异常回放。"""

    def __init__(self):
        self.history: list[tuple[str, tuple]] = []
        self._script: list[tuple[str, Any]] = []

    def connection(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                return _FakeConn(pool)

            async def __aexit__(self, *exc):
                return False

        return _Ctx()

    def queue(self, sql_substr: str, result):
        self._script.append((sql_substr, result))

    def next_exc(self, sql):
        for s, r in list(self._script):
            if s in sql and isinstance(r, BaseException):
                self._script.remove((s, r))
                return r
        return None

    def next_cursor(self, sql):
        for s, r in list(self._script):
            if s in sql and not isinstance(r, BaseException):
                self._script.remove((s, r))
                return _FakeCursor(row=r)
        return _FakeCursor()

    def last(self):
        return self.history[-1]


def _pg_error(sqlstate: str):
    e = Exception(sqlstate)
    e.sqlstate = sqlstate
    return e


# ---------------------------------------------------------------------------
# conversations（migration 013 / D11 选项 C）
# ---------------------------------------------------------------------------

async def test_claim_first_registration_inserts():
    pool = _FakePool()
    pool.queue("RETURNING 1", (1,))
    ok = await conv.claim_conversation(pool, "t-1", org_id="o1", user_id="u1", workspace_id="w1")
    assert ok is True
    sql, params = pool.last()
    assert sql.startswith("INSERT INTO conversations")
    assert "ON CONFLICT (thread_id) DO UPDATE" in sql
    # 单语句判据（§9.6-5）：WHERE 归属匹配 + RETURNING，无先 SELECT
    assert "WHERE conversations.org_id = EXCLUDED.org_id" in sql
    assert "RETURNING 1" in sql
    assert "SELECT 1 FROM conversations" not in sql
    assert params == ("t-1", "o1", "u1", "w1", "")


async def test_claim_cross_org_rejected():
    """§9.6-5 反证：归属不匹配 ⇒ RETURNING 0 行（row=None）⇒ 拒绝，非静默新建。"""
    pool = _FakePool()
    pool.queue("RETURNING 1", None)  # DO UPDATE WHERE 不命中 ⇒ 0 行
    with pytest.raises(conv.ConversationOwnershipMismatch):
        await conv.claim_conversation(pool, "t-1", org_id="attacker", user_id="u2")


async def test_claim_cross_user_rejected_when_owned():
    pool = _FakePool()
    pool.queue("RETURNING 1", None)
    with pytest.raises(conv.ConversationOwnershipMismatch):
        await conv.claim_conversation(pool, "t-1", org_id="o1", user_id="intruder")


async def test_claim_null_user_owner_passes_org_only():
    """中间态（014b 前）：属主 user_id NULL 的行，org 匹配即放行。"""
    pool = _FakePool()
    pool.queue("RETURNING 1", (1,))
    ok = await conv.claim_conversation(pool, "t-1", org_id="o1", user_id="newcomer")
    assert ok is True


async def test_claim_pool_none_returns_false():
    assert await conv.claim_conversation(None, "t", org_id="o") is False


async def test_claim_invalid_args_fail_fast():
    with pytest.raises(ValueError):
        await conv.claim_conversation(_FakePool(), "", org_id="o")
    with pytest.raises(ValueError):
        await conv.claim_conversation(_FakePool(), "t", org_id="")


async def test_get_conversation_returns_row_dict():
    pool = _FakePool()
    row = ("t-1", "o1", "u1", "w1", "标题", "2026-10-23", "2026-10-23")
    pool.queue("FROM conversations WHERE thread_id", row)
    out = await conv.get_conversation(pool, "t-1")
    assert out["org_id"] == "o1" and out["user_id"] == "u1" and out["title"] == "标题"


# ---------------------------------------------------------------------------
# workspaces 注册（014a org_id/visibility 落列 + 渐进降级）
# ---------------------------------------------------------------------------

async def test_register_writes_org_and_visibility():
    pool = _FakePool()
    pool.queue("SELECT 1 FROM workspaces", None)  # 未注册
    await register_workspace(pool, "ws-1", "t-1")
    sql, params = pool.last()
    assert "INSERT INTO workspaces" in sql
    assert "org_id" in sql and "visibility" in sql
    assert params == ("t-1", "ws-1", "t-1")  # org 同值域 = tenant


async def test_register_degrades_on_missing_column():
    """渐进窗口：014a 未应用（42703 undefined_column）⇒ 按 007 旧形态重写。"""
    pool = _FakePool()
    pool.queue("SELECT 1 FROM workspaces", None)
    pool.queue("INSERT INTO workspaces", _pg_error("42703"))
    await register_workspace(pool, "ws-1", "t-1")
    sql, params = pool.last()
    assert "org_id" not in sql and "visibility" not in sql
    assert params == ("t-1", "ws-1")


async def test_register_real_failure_not_swallowed():
    """真故障（非 42P01/42703）照抛——降级不等于 fail-open。"""
    pool = _FakePool()
    pool.queue("SELECT 1 FROM workspaces", None)
    pool.queue("INSERT INTO workspaces", _pg_error("57P01"))
    with pytest.raises(Exception):
        await register_workspace(pool, "ws-1", "t-1")


# ---------------------------------------------------------------------------
# trajectory 三列（migration 015 / G8）
# ---------------------------------------------------------------------------

def _record(**over):
    base = dict(execution_id="e-1", session_id="s-1", planner="p", tenant_id="t-1", org_id="o-1", user_id="u-1")
    base.update(over)
    return TrajectoryRecord(**base)


async def test_trajectory_save_writes_scope_columns():
    pool = _FakePool()
    store = PgTrajectoryStore(pool)
    await store.save(_record())
    sql, params = pool.last()
    for col in ("tenant_id", "org_id", "user_id"):
        assert col in sql, f"save SQL 缺归属列 {col}"
    assert params[-3:] == ("t-1", "o-1", "u-1")


async def test_trajectory_save_degrades_on_missing_columns():
    """015 未应用（42703）⇒ 旧列清单重写，主体不丢。"""
    pool = _FakePool()
    pool.queue("INSERT INTO trajectories", _pg_error("42703"))
    store = PgTrajectoryStore(pool)
    await store.save(_record())
    sql, params = pool.last()
    assert "tenant_id" not in sql
    assert len(params) == 9  # 旧形态：created_at 走 now() 不占位


async def test_trajectory_save_real_failure_raises():
    pool = _FakePool()
    pool.queue("INSERT INTO trajectories", _pg_error("57P01"))
    with pytest.raises(Exception):
        await PgTrajectoryStore(pool).save(_record())


def test_models_carry_scope_fields():
    r = _record()
    assert r.tenant_id == "t-1" and r.org_id == "o-1" and r.user_id == "u-1"
    d = r.to_dict()
    assert "tenant_id" in d
