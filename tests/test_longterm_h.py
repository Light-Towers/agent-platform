"""优化 H：长期记忆质量升级单测（三层抽取 + 三分存储 + consolidation/forgetting）。

不连真实 PG：用 monkeypatch 替换 DB 层与 embedder，验证
- 配置开关默认 False（退化路径与旧行为一致）；
- extract_memory_facts 解析 LLM JSON 输出、容错；
- recall_typed 分层加权融合排序；
- remember_fact / consolidate_memories 的写入与惰性淘汰逻辑（经 mock 池）。
"""

from types import SimpleNamespace

import pytest


# --- fake psycopg 池（async 上下文管理器 + execute/fetchall）---
class _FakeCur:
    def __init__(self, rows=None):
        self._rows = rows or []
        self.rowcount = len(self._rows)

    async def execute(self, *a, **k):
        return None

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows=None):
        self._cur = _FakeCur(rows)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def execute(self, *a, **k):
        return self._cur

    def __getattr__(self, name):
        # 透传 fetchall/rowcount 到内部 cursor
        return getattr(self._cur, name)


class _FakePool:
    def __init__(self, rows=None):
        self._rows = rows

    def connection(self):
        return _FakeConn(self._rows)


class _FakeSettings:
    def __init__(self, memory_extraction_enabled=False, memory_forget_threshold=0.1,
                 vector_dim=512, database_url=""):
        self.memory_extraction_enabled = memory_extraction_enabled
        self.memory_forget_threshold = memory_forget_threshold
        self.vector_dim = vector_dim
        self.database_url = database_url


@pytest.fixture
def patch_settings(monkeypatch):
    s = _FakeSettings()
    monkeypatch.setattr("app.config.get_settings", lambda: s)
    return s


def test_default_extraction_disabled(patch_settings):
    # 默认关闭：保持旧行为（退化存原文 / 走内核降级）
    assert patch_settings.memory_extraction_enabled is False
    assert patch_settings.memory_forget_threshold == 0.1


async def test_extract_memory_facts_parses_json(patch_settings, monkeypatch):
    import app.memory.longterm as l

    class _FakeLLM:
        async def ainvoke(self, prompt):
            return SimpleNamespace(
                content='[{"type":"semantic","importance":0.9,'
                '"fact":"用户是财务，偏好简洁报表"}]'
            )

    facts = await l.extract_memory_facts(_FakeLLM(), "问题", "回答")
    assert len(facts) == 1
    assert facts[0]["type"] == "semantic"
    assert abs(facts[0]["importance"] - 0.9) < 1e-6
    assert "财务" in facts[0]["fact"]


async def test_extract_memory_facts_handles_fenced_json(patch_settings, monkeypatch):
    import app.memory.longterm as l

    class _FakeLLM:
        async def ainvoke(self, prompt):
            return SimpleNamespace(
                content='```json\n[{"type":"procedural","importance":0.7,"fact":"报表用X模板"}]\n```'
            )

    facts = await l.extract_memory_facts(_FakeLLM(), "q", "a")
    assert facts[0]["type"] == "procedural"


async def test_extract_memory_facts_robust_to_garbage(patch_settings, monkeypatch):
    import app.memory.longterm as l

    class _FakeLLM:
        async def ainvoke(self, prompt):
            return SimpleNamespace(content="不是合法 json")

    # 不抛，返回空
    assert await l.extract_memory_facts(_FakeLLM(), "q", "a") == []


async def test_extract_memory_facts_none_llm(patch_settings, monkeypatch):
    import app.memory.longterm as l

    assert await l.extract_memory_facts(None, "q", "a") == []


async def test_recall_typed_weights_and_ranks(patch_settings, monkeypatch):
    from datetime import datetime, timedelta, timezone

    import app.memory.memory_backend as mb

    # 准备带类型的假召回（content, memory_type, importance, created_at）
    now = datetime.now(timezone.utc)
    rows = [
        ("episodic 旧事", "episodic", 0.9, now - timedelta(days=40)),
        ("semantic 偏好", "semantic", 0.9, now - timedelta(days=1)),
        ("procedural 方法", "procedural", 0.9, now - timedelta(days=1)),
    ]
    # mock 其依赖的 vector_search_memories（在 memory_backend 模块内调用）
    monkeypatch.setattr(
        mb, "vector_search_memories",
        lambda pool, ws, emb, k: _async(rows),
    )
    monkeypatch.setattr(mb, "embed_memory", lambda t: [0.0] * 512)

    result = await mb.recall_typed(_FakePool(), "ws1", "q", k=3)
    # procedural/semantic 应排在 episodic(旧) 之前
    assert result[0].startswith("procedural") or result[0].startswith("semantic")
    assert "episodic" not in result[0]


async def test_remember_fact_writes_typed(patch_settings, monkeypatch):
    # 验证 remember_fact 把带类型记录 INSERT（mock 池捕获 SQL）
    import app.memory.memory_backend as mb

    captured = {}

    class _CaptureConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, sql, params):
            captured["sql"] = sql
            captured["params"] = params
            return _FakeCur()

    class _CapturePool:
        def connection(self):
            return _CaptureConn()

    monkeypatch.setattr("app.memory.memory_backend.embed_memory", lambda t: [0.1] * 512)

    await mb.remember_fact(_CapturePool(), "ws1", "用户是财务", "semantic", 0.8)
    assert "INSERT INTO memories" in captured["sql"]
    assert captured["params"][0] == "ws1"      # workspace_id 作 user_id
    assert captured["params"][1] == "用户是财务"
    assert captured["params"][3] == "semantic"
    assert abs(captured["params"][4] - 0.8) < 1e-6


async def test_remember_fact_clamps_type_and_importance(patch_settings, monkeypatch):
    import app.memory.memory_backend as mb

    captured = {}

    class _CaptureConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, sql, params):
            captured["params"] = params
            return _FakeCur()

    class _CapturePool:
        def connection(self):
            return _CaptureConn()

    monkeypatch.setattr("app.memory.memory_backend.embed_memory", lambda t: [0.0] * 512)

    # 非法类型 → 退化 semantic；importance 超界 → 截断
    await mb.remember_fact(_CapturePool(), "ws", "f", "bogus", 5.0)
    assert captured["params"][3] == "semantic"
    assert captured["params"][4] == 1.0


async def test_consolidate_deletes_low_value_old(patch_settings, monkeypatch):
    import app.memory.memory_backend as mb

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

    deleted = await mb.consolidate_memories(_CapturePool(), "ws1", forget_threshold=0.1)
    assert deleted == 3
    assert "DELETE FROM memories" in captured["sql"]
    assert captured["params"] == ("ws1", 0.1)


async def test_recall_falls_back_to_core_when_disabled(patch_settings, monkeypatch):
    # memory_extraction_enabled=False：recall 走内核降级路径（pool=None → 内核自建池）
    import app.memory.longterm as l

    called = {}

    class _FakeCoreBackend:
        async def recall(self, pool, user_id, question, k=3):
            called["recall"] = (user_id, question)
            return ["历史记忆"]

    monkeypatch.setattr(
        "app.memory.memory_backend.get_default_backend", lambda: _FakeCoreBackend()
    )
    # 强制退化路径：pool=None
    res = await l.recall(None, "ws-x", "问题")
    assert res == ["历史记忆"]
    assert called["recall"][0] == "ws-x"


async def test_recall_forwards_to_recall_typed_when_enabled(patch_settings, monkeypatch):
    # 优化 H 类型增强路径：enabled 且 pool 非空时，门面必须转发到 _mb.recall_typed
    # （回归：曾误写裸 recall_typed 导致 NameError）
    import app.memory.longterm as l

    patch_settings.memory_extraction_enabled = True
    # longterm 用 `from app.config import get_settings` 绑定副本，需直接 patch 模块内引用
    monkeypatch.setattr("app.memory.longterm.get_settings", lambda: patch_settings)
    spy = {"called": None}

    async def _fake_recall_typed(pool, ws, q, k=3):
        spy["called"] = (ws, q, k)
        return ["typed-mem"]

    monkeypatch.setattr("app.memory.memory_backend.recall_typed", _fake_recall_typed)

    class _Pool:
        pass

    res = await l.recall(_Pool(), "ws-typed", "q", k=2)
    assert res == ["typed-mem"]
    assert spy["called"] == ("ws-typed", "q", 2)


async def test_remember_forwards_to_remember_fact_when_enabled(patch_settings, monkeypatch):
    # 优化 H：提供 facts 时门面必须逐条转发到 _mb.remember_fact
    # （回归：曾误写裸 remember_fact 导致 NameError）
    import app.memory.longterm as l

    patch_settings.memory_extraction_enabled = True
    monkeypatch.setattr("app.memory.longterm.get_settings", lambda: patch_settings)
    spy = {"facts": []}

    async def _fake_remember_fact(pool, ws, fact, mtype, importance):
        spy["facts"].append((ws, fact, mtype, importance))

    monkeypatch.setattr("app.memory.memory_backend.remember_fact", _fake_remember_fact)

    class _Pool:
        pass

    facts = [
        {"type": "semantic", "importance": 0.8, "fact": "用户是财务"},
        {"type": "episodic", "importance": 0.5, "fact": "上周做了报表"},
    ]
    await l.remember(_Pool(), "ws-typed", "原文不存", facts=facts)
    assert spy["facts"] == [
        ("ws-typed", "用户是财务", "semantic", 0.8),
        ("ws-typed", "上周做了报表", "episodic", 0.5),
    ]


def _async(value):
    async def _coro():
        return value
    return _coro()
