# -*- coding: utf-8 -*-
"""ADR-0004 阶段2：deepagents 类型化记忆封装单测（mock psycopg 池）。

验证：
- SEMANTIC_MEMORY_TYPED=true 时，typed 封装委托内核 typed API（recall/remember/consolidate/forget）；
- SEMANTIC_MEMORY_TYPED=false（默认）时，回退内核旧门面（零行为变更），consolidate/forget 无操作；
- embed_memory 用 agent-core embedder 单例（无实际模型加载时 mock）。

deepagents 的 pytest 配置 asyncio_mode=auto，async 测试无需装饰器。
"""

from __future__ import annotations

import agent_core.memory.typed as typed_core
import agent.memory.semantic_memory as sm


class _FakePool:
    """mock 宿主 psycopg 池（仅需 connection() 上下文入口，typed 调用被 mock 拦截）。"""

    def connection(self):
        raise AssertionError("typed 调用应被 mock 拦截，不应真正取连接")


# --- 开关开启：委托内核 typed API ------------------------------------------

async def test_recall_typed_delegates_to_core_typed(monkeypatch):
    monkeypatch.setattr(sm, "semantic_memory_typed_enabled", lambda: True)
    captured = {}

    async def _fake_core_recall(pool, user_id, question, k, weights, embedding):
        captured.update(
            pool=pool, user_id=user_id, question=question, k=k,
            weights=weights, embedding=embedding,
        )
        from agent_core.memory.typed import TypedMemory, MemoryType

        return [TypedMemory(content="x", memory_type=MemoryType.SEMANTIC, importance=0.5)]

    monkeypatch.setattr(sm, "_core_recall_typed", _fake_core_recall)
    monkeypatch.setattr(sm, "embed_memory", lambda t: [0.1, 0.2])

    pool = _FakePool()
    result = await sm.recall_typed(pool, "u1", "q", k=5, weights=[("episodic", 2.0)])

    assert captured["pool"] is pool
    assert captured["user_id"] == "u1"
    assert captured["k"] == 5
    assert captured["weights"] == [("episodic", 2.0)]
    assert captured["embedding"] == [0.1, 0.2]
    assert result[0].content == "x"


async def test_remember_fact_delegates_to_core_typed(monkeypatch):
    monkeypatch.setattr(sm, "semantic_memory_typed_enabled", lambda: True)
    captured = {}

    async def _fake_core_remember(pool, user_id, fact, memory_type, importance, embedding):
        captured.update(
            pool=pool, user_id=user_id, fact=fact,
            memory_type=memory_type, importance=importance, embedding=embedding,
        )

    monkeypatch.setattr(sm, "_core_remember_typed", _fake_core_remember)
    monkeypatch.setattr(sm, "embed_memory", lambda t: [0.3, 0.4])

    pool = _FakePool()
    await sm.remember_fact(pool, "u1", "用户是财务", "procedural", 0.9)

    assert captured["fact"] == "用户是财务"
    assert captured["memory_type"] == "procedural"
    assert captured["importance"] == 0.9
    assert captured["embedding"] == [0.3, 0.4]


async def test_consolidate_and_forget_delegate_when_enabled(monkeypatch):
    monkeypatch.setattr(sm, "semantic_memory_typed_enabled", lambda: True)
    calls = {"consolidate": 0, "forget": 0}

    async def _fake_consolidate(user_id, pool, forget_threshold):
        calls["consolidate"] += 1
        assert user_id == "u1" and pool is not None
        return 2

    async def _fake_forget(user_id, pool, memory_id):
        calls["forget"] += 1
        assert memory_id == 7
        return True

    monkeypatch.setattr(sm, "_core_consolidate", _fake_consolidate)
    monkeypatch.setattr(sm, "_core_forget", _fake_forget)

    pool = _FakePool()
    assert await sm.consolidate(pool, "u1", 0.1) == 2
    assert await sm.forget(pool, "u1", 7) is True
    assert calls == {"consolidate": 1, "forget": 1}


# --- 开关关闭：回退内核旧门面（零行为变更）-------------------------------

async def test_fallback_recall_uses_old_recall(monkeypatch):
    monkeypatch.setattr(sm, "semantic_memory_typed_enabled", lambda: False)
    captured = {}

    class _FakeBackend:
        pass

    monkeypatch.setattr(sm, "get_default_backend", lambda: _FakeBackend())

    async def _fake_recall(user_id, query, backend, limit):
        captured.update(user_id=user_id, query=query, backend=backend, limit=limit)
        return ["旧记忆A", "旧记忆B"]

    monkeypatch.setattr(sm, "recall_memories", _fake_recall)

    pool = _FakePool()
    result = await sm.recall_typed(pool, "u1", "q", k=3)

    assert captured["user_id"] == "u1"
    assert captured["query"] == "q"
    assert isinstance(captured["backend"], _FakeBackend)
    assert captured["limit"] == 3
    # 回退路径包装为 TypedMemory，类型语义默认 semantic
    assert [m.content for m in result] == ["旧记忆A", "旧记忆B"]
    assert all(m.memory_type.value == "semantic" for m in result)


async def test_fallback_remember_uses_old_remember(monkeypatch):
    monkeypatch.setattr(sm, "semantic_memory_typed_enabled", lambda: False)
    captured = {}

    class _FakeBackend:
        pass

    monkeypatch.setattr(sm, "get_default_backend", lambda: _FakeBackend())

    async def _fake_remember(user_id, fact, backend):
        captured.update(user_id=user_id, fact=fact, backend=backend)

    monkeypatch.setattr(sm, "remember_memory", _fake_remember)

    pool = _FakePool()
    await sm.remember_fact(pool, "u1", "事实", "procedural", 0.9)

    assert captured["user_id"] == "u1"
    assert captured["fact"] == "事实"
    assert isinstance(captured["backend"], _FakeBackend)


async def test_fallback_remember_noop_without_backend(monkeypatch):
    monkeypatch.setattr(sm, "semantic_memory_typed_enabled", lambda: False)
    monkeypatch.setattr(sm, "get_default_backend", lambda: None)
    called = {"remember": False}
    monkeypatch.setattr(sm, "remember_memory", lambda **k: called.__setitem__("remember", True))

    pool = _FakePool()
    await sm.remember_fact(pool, "u1", "事实")  # 不应调用旧门面
    assert called["remember"] is False


async def test_consolidate_and_forget_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(sm, "semantic_memory_typed_enabled", lambda: False)
    pool = _FakePool()
    # typed 关闭时保持零行为变更
    assert await sm.consolidate(pool, "u1") == 0
    assert await sm.forget(pool, "u1", 7) is False


# --- embed_memory 使用 agent-core embedder 单例 ---------------------------

def test_embed_memory_calls_core_embedder(monkeypatch):
    captured = {}

    class _FakeProvider:
        def embed(self, texts):
            captured["texts"] = texts
            return [[0.5, 0.6]]

    import agent_core.memory.embedder as emb_mod

    monkeypatch.setattr(emb_mod, "get_embedder", lambda: _FakeProvider())
    vec = sm.embed_memory("hi")
    assert captured["texts"] == ["hi"]
    assert vec == [0.5, 0.6]
