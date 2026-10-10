"""/history 读侧真实契约用例（缺陷：调了 checkpointer 上不存在的 alist_messages）。

刻意**不用假 checkpointer 冒充**：上一版之所以能一直绿着坏，就是因为读取路径没有任何真实覆盖，
而宽 except 把 AttributeError 盖成「空历史 + HTTP 200」。方案与实测读数见
`docs/plans/plan-history-read-uses-nonexistent-checkpointer-api-2026-10-10.md`。
"""

from __future__ import annotations

import pytest
from agent_server.api import session_router
from agent_server.memory import recall_exact, thread_persist
from langgraph.checkpoint.memory import InMemorySaver


async def _append_two_turns(saver: InMemorySaver, thread_id: str) -> None:
    await thread_persist.append_thread(saver, thread_id, "上个月销售额多少", "华东 120 万")
    await thread_persist.append_thread(saver, thread_id, "那华东呢", "华东明细见资料第 3 节")


class TestReadAgainstRealCheckpointer:
    async def test_two_turns_read_back(self):
        saver = InMemorySaver()
        await _append_two_turns(saver, "tenant-default")

        records = await recall_exact.get_thread_history(saver, "tenant-default")

        assert [(r["role"], r["content"]) for r in records] == [
            ("user", "上个月销售额多少"),
            ("assistant", "华东 120 万"),
            ("user", "那华东呢"),
            ("assistant", "华东明细见资料第 3 节"),
        ]
        assert [r["index"] for r in records] == [0, 1, 2, 3]
        # 每条都有可回溯的消息 id；无写入方带时间戳，读侧不得造一个（底线 5）
        assert all(r["id"] for r in records)
        assert all(r["created_at"] is None for r in records)

    async def test_keyword_and_limit_keep_their_semantics(self):
        saver = InMemorySaver()
        await _append_two_turns(saver, "t1")

        hits = await recall_exact.get_thread_history(saver, "t1", keyword="华东")
        assert [r["content"] for r in hits] == [
            "华东 120 万",
            "那华东呢",
            "华东明细见资料第 3 节",
        ]

        last_two = await recall_exact.get_thread_history(saver, "t1", limit=2)
        assert [r["content"] for r in last_two] == ["那华东呢", "华东明细见资料第 3 节"]

    async def test_unknown_thread_is_empty_not_an_error(self):
        saver = InMemorySaver()
        await _append_two_turns(saver, "t1")
        assert await recall_exact.get_thread_history(saver, "别的会话") == []

    async def test_missing_checkpointer_is_empty(self):
        assert await recall_exact.get_thread_history(None, "t1") == []


class TestReadFailureIsNotSilentlyEmpty:
    """非空洞性：坏在读侧必须炸出来，不能又是「200 + 空数组」。"""

    class _OnlyOldApi:
        """只实现那份不存在的旧契约，用来证明读侧不再依赖它。"""

        async def alist_messages(self, config):  # pragma: no cover - 断言它不被调用
            return ["不该被读到"]

    async def test_raises_instead_of_returning_empty(self):
        with pytest.raises(AttributeError):
            await recall_exact.get_thread_history(self._OnlyOldApi(), "t1")

    async def test_search_in_thread_follows_the_same_path(self):
        with pytest.raises(AttributeError):
            await recall_exact.search_in_thread(self._OnlyOldApi(), "t1", "关键词")


class TestHistoryEndpointOverHttp:
    """HTTP 层：归属语义与 5xx 语义，都走真实 app 与真实 checkpointer。"""

    @pytest.fixture
    def make_client(self, monkeypatch):
        from contextlib import ExitStack

        import agent_core.intent.classifier as intent_classifier
        from agent_server.config import get_settings
        from agent_server.main import app
        from fastapi.testclient import TestClient

        # 意图路由直连 LocalEmbedder、不看 EMBEDDING_MODE（见 plan-intent-embedder-bypasses-provider），
        # 本组用例测的是历史读侧，故显式让语义层不可用 → 关键词降级，别把真模型加载/HF 网络拖进来。
        def _no_semantic():
            raise ImportError("本用例不走语义意图层")

        monkeypatch.setattr(intent_classifier, "_embedder", _no_semantic)

        stack = ExitStack()

        def _make(**envs):
            for k, v in envs.items():
                monkeypatch.setenv(k, v)
            get_settings.cache_clear()
            return stack.enter_context(TestClient(app))

        yield _make
        stack.close()
        get_settings.cache_clear()

    def test_real_turn_shows_up_in_history(self, make_client):
        client = make_client(API_KEY="k-http", GUARD_ENABLED="true")
        r = client.post(
            "/query",
            json={"query": "我们上个月的销售额是多少", "session_id": "客户端乱填的会话号"},
            headers={"X-API-Key": "k-http"},
        )
        assert r.status_code == 200

        h = client.get(
            "/history", params={"session_id": "随便一个值"}, headers={"X-API-Key": "k-http"}
        )
        assert h.status_code == 200, h.text
        body = h.json()
        # 服务端断言会话：客户端传入的会话号不参与归属
        assert body["thread_id"] == "tenant-default"
        assert body["count"] == len(body["items"])
        assert body["count"] >= 2
        assert "我们上个月的销售额是多少" in " ".join(it["content"] for it in body["items"])

    def test_read_failure_surfaces_as_503_not_empty_200(self, make_client):
        from agent_server.main import app

        client = make_client(API_KEY="k-503")
        good = app.state.checkpointer

        class _Broken:
            async def aget_tuple(self, config):
                raise RuntimeError("存储不可达")

        app.state.checkpointer = _Broken()
        try:
            h = client.get("/history", params={"session_id": "x"}, headers={"X-API-Key": "k-503"})
            assert h.status_code == 503
            assert h.json()["detail"] == "HISTORY_READ_FAILED"
        finally:
            app.state.checkpointer = good

    def test_503_when_checkpointer_absent(self, make_client):
        from agent_server.main import app

        client = make_client(API_KEY="k-none")
        good = app.state.checkpointer
        del app.state.checkpointer
        try:
            h = client.get("/history", params={"session_id": "x"}, headers={"X-API-Key": "k-none"})
            assert h.status_code == 503
            assert h.json()["detail"] == "CHECKPOINTER_UNAVAILABLE"
        finally:
            app.state.checkpointer = good


def test_module_no_longer_references_the_phantom_api():
    """源码级反证：精确回忆路径里不该再有对 `alist_messages` 的**调用**
    （注释与 docstring 里作为历史成因提到它是允许的，别把说明文字也禁掉）。"""
    import inspect

    src = inspect.getsource(recall_exact) + inspect.getsource(session_router)
    assert "alist_messages(" not in src
