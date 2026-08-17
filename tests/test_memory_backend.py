"""MemoryBackend 协议与后端委托测试（语义记忆统一到内核 agent_core）。

验证：
  - app.memory.memory_backend 不再持有本地 PgVectorMemoryBackend /
    CompositeMemoryBackend（去重，统一收口到内核）。
  - 内存模式（无 DATABASE_URL）下 default_backend 降级为 None，recall 返回空。
  - app 的 embed 被注入内核 PgVectorMemoryBackend（512 维，与 memories 表对齐）。
  - 内核 MemoryBackend 契约可被运行时检查（runtime_checkable Protocol）。
"""

from app.memory.memory_backend import get_default_backend
from agent_core.memory.backend import MemoryBackend


def test_memory_backend_module_no_local_impl():
    import app.memory.memory_backend as m

    # 无债务：本地 PgVectorMemoryBackend / CompositeMemoryBackend 已删除
    assert not hasattr(m, "PgVectorMemoryBackend")
    assert not hasattr(m, "CompositeMemoryBackend")


async def test_recall_empty_in_memory_mode(monkeypatch):
    # 内存模式：无 DATABASE_URL → 后端降级 None，recall 返回空
    monkeypatch.setattr(
        "app.memory.memory_backend._resolve_default_backend",
        lambda: None,
    )
    import app.memory.longterm as l

    assert await l.recall(None, "u1", "q") == []


def test_default_backend_none_without_db(monkeypatch):
    # 未配置 DB 时降级为 None（不抛、不连库）
    monkeypatch.setattr(
        "app.config.get_settings", lambda: _FakeSettings(database_url="")
    )
    backend = get_default_backend()
    assert backend is None


def test_default_backend_delegates_to_core_pg(monkeypatch):
    # 配置 DB 时不抛，且返回内核 PgVectorMemoryBackend 实例
    from agent_core.memory.vector_backend import PgVectorMemoryBackend

    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: _FakeSettings(database_url="postgresql://x@localhost/db"),
    )
    import app.memory.memory_backend as m

    m.default_backend = None  # 强制重新解析
    backend = m._resolve_default_backend()
    assert isinstance(backend, PgVectorMemoryBackend)
    assert backend._table == "memories"
    assert backend._tenant_id is None
    # app embedder 注入（512 维，对应 settings.vector_dim）
    assert backend._embedder.dim == 512


class _FakeSettings:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.vector_dim = 512


def test_protocol_runtime_checkable():
    # 内核 MemoryBackend 契约可被 runtime_checkable 检查（注入 MockEmbedder 避免装 asyncpg/模型）
    from agent_core.memory.embedder import MockEmbedder
    from agent_core.memory.vector_backend import PgVectorMemoryBackend

    assert isinstance(
        PgVectorMemoryBackend(database_url="x", tenant_id=None, embedder=MockEmbedder()),
        MemoryBackend,
    )
