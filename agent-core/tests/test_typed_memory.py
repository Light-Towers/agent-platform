# -*- coding: utf-8 -*-
"""ADR-0004 阶段 1：类型化记忆内核单测（框架无关，无 DB 无 LLM）。

验证：
- 加权融合排序：procedural/semantic 高于 episodic；
- 双曲时间衰减单调性：越旧分越低；
- consolidate 遗忘阈值：低价值且超 30 天被删，rowcount 正确；
- forget 删除：命中返回 True，未命中返回 False；
- 类型归一化 / importance 截断 / weights 覆盖。

一律用 fake psycopg 池（async 上下文管理器 + execute/fetchall/rowcount），
不连真实 PG，不引 psycopg / langchain / openai。
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace

import pytest

from agent_core.memory.typed import (
    MemoryType,
    TypedMemory,
    _normalize_weights,
    _score_memory,
    _time_decay,
    consolidate,
    forget,
    recall_typed,
    remember_typed,
)


# --- fake psycopg 池 -------------------------------------------------------

class _FakeCur:
    def __init__(self, rows=None, rowcount=0):
        self._rows = rows or []
        self.rowcount = rowcount

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows=None, rowcount=0):
        self._cur = _FakeCur(rows, rowcount)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def execute(self, *a, **k):
        return self._cur

    def __getattr__(self, name):
        return getattr(self._cur, name)


class _FakePool:
    def __init__(self, rows=None, rowcount=0):
        self._rows = rows
        self._rowcount = rowcount

    def connection(self):
        return _FakeConn(self._rows, self._rowcount)


def _async(value):
    async def _coro():
        return value
    return _coro()


# --- 加权融合排序 ----------------------------------------------------------

def test_type_weights_rank_procedural_over_episodic():
    now = datetime.datetime.now(datetime.timezone.utc)
    w = _normalize_weights(None)
    ep = _score_memory(MemoryType.EPISODIC, 0.9, now, now, w)
    se = _score_memory(MemoryType.SEMANTIC, 0.9, now, now, w)
    pr = _score_memory(MemoryType.PROCEDURAL, 0.9, now, now, w)
    assert pr > se > ep
    # 默认系数
    assert abs(pr - 0.9 * 1.2) < 1e-9
    assert abs(se - 0.9 * 1.1) < 1e-9
    assert abs(ep - 0.9 * 1.0) < 1e-9


def test_weights_override_via_argument():
    now = datetime.datetime.now(datetime.timezone.utc)
    w = _normalize_weights([("episodic", 2.0)])
    ep = _score_memory(MemoryType.EPISODIC, 1.0, now, now, w)
    se = _score_memory(MemoryType.SEMANTIC, 1.0, now, now, w)
    assert ep > se  # 覆盖后 episodic 反超


# --- 双曲时间衰减单调性 ----------------------------------------------------

def test_time_decay_monotonic_and_bounded():
    base = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    d0 = _time_decay(base, base)
    d10 = _time_decay(base, base + datetime.timedelta(days=10))
    d30 = _time_decay(base, base + datetime.timedelta(days=30))
    d100 = _time_decay(base, base + datetime.timedelta(days=100))
    # 越旧 decay 越小
    assert d0 > d10 > d30 > d100
    # 边界：当前为 1.0
    assert abs(d0 - 1.0) < 1e-9
    # 30 天约 0.77
    assert abs(d30 - 1.0 / (1 + 0.01 * 30)) < 1e-9
    # 非负且收敛
    assert d100 > 0


def test_time_decay_none_returns_one():
    now = datetime.datetime.now(datetime.timezone.utc)
    assert _time_decay(None, now) == 1.0


# --- 类型归一化 / importance 截断 ------------------------------------------

def test_memory_type_normalize_invalid_falls_back_semantic():
    assert MemoryType.normalize("BOGUS") is MemoryType.SEMANTIC
    assert MemoryType.normalize("EPISODIC") is MemoryType.EPISODIC
    assert MemoryType.normalize(MemoryType.PROCEDURAL) is MemoryType.PROCEDURAL


# --- recall_typed 端到端（fake 池）-----------------------------------------

async def test_recall_typed_ranks_by_weighted_score(monkeypatch):
    # 开启 typed 开关以走加权路径
    monkeypatch.setattr(
        "agent_core.memory.typed.semantic_memory_typed_enabled", lambda: True
    )
    now = datetime.datetime.now(datetime.timezone.utc)
    rows = [
        ("episodic 旧事", "episodic", 0.9, now - datetime.timedelta(days=40)),
        ("semantic 偏好", "semantic", 0.9, now - datetime.timedelta(days=1)),
        ("procedural 方法", "procedural", 0.9, now - datetime.timedelta(days=1)),
    ]
    monkeypatch.setattr(
        "agent_core.memory.typed._vector_search_memories",
        lambda pool, user_id, embedding, k: _async(rows),
    )
    result = await recall_typed(_FakePool(), "u1", "q", k=3, embedding=[0.0] * 8)
    assert isinstance(result[0], TypedMemory)
    assert result[0].content.startswith("procedural") or result[0].content.startswith(
        "semantic"
    )
    assert "episodic" not in result[0].content
    assert len(result) == 3


async def test_recall_typed_empty_returns_empty(monkeypatch):
    monkeypatch.setattr(
        "agent_core.memory.typed._vector_search_memories",
        lambda pool, user_id, embedding, k: _async([]),
    )
    result = await recall_typed(_FakePool(), "u1", "q", k=3, embedding=[0.0] * 8)
    assert result == []


async def test_recall_typed_requires_embedding():
    with pytest.raises(ValueError):
        await recall_typed(_FakePool(), "u1", "q", k=3, embedding=None)


# --- remember_typed（fake 池，校验列顺序/SQL）------------------------------

async def test_remember_typed_inserts_typed_columns(monkeypatch):
    captured = {}

    class _CaptureCur:
        def fetchall(self):
            return []

    class _CaptureConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, sql, params):
            captured["sql"] = sql
            captured["params"] = params
            return _CaptureCur()

    class _CapturePool:
        def connection(self):
            return _CaptureConn()

    await remember_typed(
        _CapturePool(), "u1", "用户是财务", "semantic", 0.8, embedding=[0.1] * 8
    )
    assert "INSERT INTO memories" in captured["sql"]
    # 列顺序：user_id, content, embedding, memory_type, importance
    assert captured["params"][0] == "u1"
    assert captured["params"][1] == "用户是财务"
    assert captured["params"][3] == "semantic"
    assert abs(captured["params"][4] - 0.8) < 1e-9


async def test_remember_typed_clamps_type_and_importance(monkeypatch):
    captured = {}

    class _CaptureCur:
        def fetchall(self):
            return []

    class _CaptureConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, sql, params):
            captured["params"] = params
            return _CaptureCur()

    class _CapturePool:
        def connection(self):
            return _CaptureConn()

    await remember_typed(
        _CapturePool(), "u", "f", "bogus", 5.0, embedding=[0.0] * 8
    )
    # 非法类型 → semantic；importance 超界 → 1.0
    assert captured["params"][3] == "semantic"
    assert captured["params"][4] == 1.0


async def test_remember_typed_requires_embedding():
    with pytest.raises(ValueError):
        await remember_typed(_FakePool(), "u", "f", "semantic", 0.5, embedding=None)


# --- consolidate 遗忘阈值（fake 池，rowcount）------------------------------

async def test_consolidate_deletes_low_value_old(monkeypatch):
    captured = {}

    class _CaptureCur:
        rowcount = 3

        def fetchall(self):
            return []

    class _CaptureConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, sql, params):
            captured["sql"] = sql
            captured["params"] = params
            return _CaptureCur()

    class _CapturePool:
        def connection(self):
            return _CaptureConn()

    deleted = await consolidate("ws1", _CapturePool(), forget_threshold=0.1)
    assert deleted == 3
    assert "DELETE FROM memories" in captured["sql"]
    assert captured["params"] == ("ws1", 0.1)
    # 含 30 天窗口与 importance 阈值条件
    assert "importance <" in captured["sql"]
    assert "interval '30 days'" in captured["sql"]


# --- forget 删除（fake 池）------------------------------------------------

async def test_forget_deletes_when_matched(monkeypatch):
    captured = {}

    class _CaptureCur:
        rowcount = 1

        def fetchall(self):
            return []

    class _CaptureConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, sql, params):
            captured["params"] = params
            return _CaptureCur()

    class _CapturePool:
        def connection(self):
            return _CaptureConn()

    ok = await forget("u1", _CapturePool(), 42)
    assert ok is True
    assert captured["params"] == ("u1", 42)


async def test_forget_returns_false_when_no_match(monkeypatch):
    class _CaptureCur:
        rowcount = 0

        def fetchall(self):
            return []

    class _CaptureConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, sql, params):
            return _CaptureCur()

    class _CapturePool:
        def connection(self):
            return _CaptureConn()

    ok = await forget("u1", _CapturePool(), 999)
    assert ok is False
