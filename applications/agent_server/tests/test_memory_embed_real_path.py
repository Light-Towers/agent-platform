"""类型化记忆 embedding 真实路径契约测试（2026-10-10）。

立项：真集群实跑每次 /query 都打「类型感知召回失败 / embed_texts() got an unexpected
keyword argument 'dim'」。既有四处用例（tests/memory/test_longterm_h.py、
tests/governance/test_workspace_isolation.py）把 ``embed_memory`` 整个 monkeypatch 成
lambda，真实函数体从未被执行 ⇒ 测试全绿与「向量算得出来」是两件事。

**本文件刻意不打任何替身**：直接调真实 ``embed_memory``，钉住
① 返回长度 == settings.vector_dim；② 在已运行的事件循环内可调用（旧缺陷之一是同步函数
里没 await 拿到 coroutine；而"顺手改成 asyncio.run"会在事件循环内死锁——两种错法都挡住）。

CI 零密钥：EMBEDDING_REQUIRE_REAL 未设时走 MockEmbedder（确定性 hash），仍验维度与时序。
方案：docs/plans/plan-memory-backend-stale-embed-signature-2026-10-10.md
"""

from __future__ import annotations


class TestEmbedMemoryRealPath:
    async def test_returns_configured_dim_without_mocks(self, monkeypatch):
        """不打替身：真实 embed_memory 必须算出 settings.vector_dim 维向量。"""
        from agent_server.config import get_settings
        from agent_server.memory.memory_backend import embed_memory

        monkeypatch.delenv("EMBEDDING_REQUIRE_REAL", raising=False)
        expected = get_settings().vector_dim

        vec = embed_memory("平台支持知识库问答与数据问数")

        assert not hasattr(vec, "__await__"), "拿到的是 coroutine：同步入口没真正执行推理"
        assert len(vec) == expected, f"记忆向量维度 {len(vec)} != settings.vector_dim {expected}"

    async def test_sync_entry_agrees_with_async_entry(self, monkeypatch):
        """sync 与 async 两条入口必须同维度（分叉即风险 2 的成因形态）。"""
        from agent_server.config import get_settings
        from agent_server.rag.embed import embed_texts, embed_texts_sync

        monkeypatch.delenv("EMBEDDING_REQUIRE_REAL", raising=False)
        texts = ["甲", "乙"]

        async_out = await embed_texts(texts)
        sync_out = embed_texts_sync(texts)

        assert len(sync_out) == len(async_out) == len(texts)
        expected = get_settings().vector_dim
        assert all(len(v) == expected for v in sync_out + async_out)

    async def test_empty_input_short_circuits(self, monkeypatch):
        from agent_server.rag.embed import embed_texts_sync

        monkeypatch.delenv("EMBEDDING_REQUIRE_REAL", raising=False)
        assert embed_texts_sync([]) == []


class TestBackendEmbedderSingleImplementation:
    def test_uses_kernel_local_fn_embedder(self, monkeypatch):
        """app 不再自带手写适配层：后端 embedder 必须是内核 LocalFnEmbedder。"""
        import agent_server.config as _cfg
        import agent_server.memory.memory_backend as mb
        from agent_core.memory.embedder import LocalFnEmbedder

        monkeypatch.setattr(_cfg, "get_settings", lambda: _cfg.Settings(database_url="postgresql://u/p@h/db"))
        monkeypatch.setattr(mb, "default_backend", None)

        backend = mb._resolve_default_backend()

        # 内核 PgVectorMemoryBackend 以私有 _embedder 承载宿主注入（vector_backend.py:79）
        assert isinstance(backend._embedder, LocalFnEmbedder), type(backend._embedder)
        assert backend._dim == _cfg.get_settings().vector_dim

    def test_stale_kwarg_shape_is_gone(self):
        """非空洞性判据：embed_texts 不接受 dim=（旧调用正是败在此处）。"""
        import inspect

        from agent_server.rag.embed import embed_texts

        assert "dim" not in inspect.signature(embed_texts).parameters
        assert inspect.iscoroutinefunction(embed_texts)
