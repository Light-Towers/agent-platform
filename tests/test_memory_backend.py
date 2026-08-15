"""MemoryBackend 协议与后端实现测试（优化 C）。

验证：PgVectorMemoryBackend 边界行为、CompositeMemoryBackend 首期等价于
pgvector 后端（namespace 路由扩展点预留），以及 Protocol 契约可被运行时检查。
"""

from app.memory.memory_backend import (
    CompositeMemoryBackend,
    MemoryBackend,
    PgVectorMemoryBackend,
)


def test_pgvector_remember_skips_when_pool_none():
    # pool=None 时直接跳过，不抛异常
    backend = PgVectorMemoryBackend()
    backend.remember(None, "u1", "some memory")  # 不应抛
    backend.remember(object(), "u1", "   ")  # 空白内容跳过


async def test_pgvector_recall_returns_empty_when_pool_none():
    backend = PgVectorMemoryBackend()
    assert await backend.recall(None, "u1", "q") == []


async def test_pgvector_recall_returns_rows(monkeypatch):
    backend = PgVectorMemoryBackend()

    class FakePool:
        def connection(self):
            raise AssertionError("不应被调用（recall 走 vector_search mock）")

    async def fake_embed_query(q):
        return [0.1, 0.2, 0.3]

    async def fake_vector_search(pool, table, col, emb, k, where, where_params):
        assert where_params == ("u1",)
        return [("记忆A",), ("记忆B",)]

    monkeypatch.setattr(
        "app.memory.memory_backend.embed_query", fake_embed_query
    )
    monkeypatch.setattr(
        "app.memory.memory_backend.vector_search", fake_vector_search
    )

    rows = await backend.recall(FakePool(), "u1", "问题", k=2)
    assert rows == ["记忆A", "记忆B"]


async def test_composite_routes_to_default_backend(monkeypatch):
    # CompositeMemoryBackend 首期所有 namespace 等价于默认 pgvector 后端
    captured = {}

    class FakeDefault:
        async def recall(self, pool, user_id, question, k=3):
            captured["ns"] = "called"
            return ["x"]

        def remember(self, pool, user_id, content):
            captured["remember"] = content

    composite = CompositeMemoryBackend(default=FakeDefault())
    assert isinstance(composite, MemoryBackend)  # runtime_checkable Protocol 成立

    result = await composite.recall(None, "u1", "q", namespace="file")
    assert result == ["x"]
    assert captured["ns"] == "called"

    composite.remember(None, "u1", "mem")
    assert captured["remember"] == "mem"


def test_default_backend_is_pgvector():
    from app.memory.memory_backend import default_backend

    assert isinstance(default_backend, PgVectorMemoryBackend)
