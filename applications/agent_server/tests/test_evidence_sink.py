# -*- coding: utf-8 -*-
"""请求级证据池测试：绑定/复位、跨 task 可见、rag 旁路写入、降级不写池。

对应 plan-image-citation-e2e-2026-11-23 §2.2 / 验收 #2「结构不丢」。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from agent_server.evidence_sink import EvidenceSink, bind_sink, current_sink, reset_sink


class TestSinkLifecycle:
    def test_default_none(self):
        assert current_sink() is None

    def test_bind_and_reset(self):
        sink, token = bind_sink()
        assert current_sink() is sink
        assert isinstance(sink, EvidenceSink)
        reset_sink(token)
        assert current_sink() is None

    async def test_cross_task_visibility(self):
        """关键不变量：gather 子 task 对同一池对象 append，父 task 读得到。

        刻意用「父 set + 子只改对象」形状，规避 Python 3.11「子 task var.set 不回传」。
        若有人把写入改成 `var.set(var.get()+...)`，这条会红。
        """
        sink, token = bind_sink()
        try:
            async def writer(i: int) -> None:
                s = current_sink()
                assert s is not None  # 子 task 继承的是同一个对象引用
                s.rag_chunks.append({"id": str(i), "source": f"doc{i}"})

            await asyncio.gather(*(writer(i) for i in range(6)))
            assert [c["id"] for c in sink.rag_chunks] == [str(i) for i in range(6)]
        finally:
            reset_sink(token)

    def test_reset_prevents_cross_request_leak(self):
        """同 worker 上：绑定→复位→后续请求读不到上一轮的池。"""
        first, token = bind_sink()
        first.rag_chunks.append({"id": "stale"})
        reset_sink(token)
        second, token2 = bind_sink()
        try:
            assert second is not first  # 新请求拿到全新池，不复用上一轮对象
            assert second.rag_chunks == []
            assert current_sink() is second
        finally:
            reset_sink(token2)


def _mock_store_with(chunks):
    store = MagicMock()
    store.retrieve = AsyncMock(return_value=chunks)
    return store


async def test_rag_query_extends_sink_with_structured_chunks():
    """rag_query 在拍平前把结构化 chunks 旁路进 sink，返回值仍是字符串（不撞既有契约）。"""
    chunks = [
        {"id": "c-1", "source": "安全规范.md", "heading": "玻璃材料", "content": "钢化玻璃 8mm", "score": 0.9},
        {"id": "c-2", "source": "安全规范.md", "heading": None, "content": "![摘要](http://minio/a.png)", "score": 0.8},
    ]
    sink, token = bind_sink()
    try:
        with patch("agent_server.subagents.rag.get_pool", return_value=MagicMock()), \
             patch("agent_server.subagents.rag.get_document_store", return_value=_mock_store_with(chunks)), \
             patch("agent_server.subagents.rag.get_settings") as mock_settings:
            mock_settings.return_value.rag_top_k = 5
            from agent_server.subagents.rag import rag_query

            result = await rag_query("test")
        assert len(result) == 2  # 既有字符串契约不变
        assert sink.rag_chunks == chunks  # 结构化旁路完整保留
    finally:
        reset_sink(token)


async def test_rag_query_without_binding_is_safe():
    """后台任务/测试直调（无 sink）时 rag_query 照常工作，不报错。"""
    chunks = [{"id": "c-1", "source": "d", "heading": "h", "content": "c", "score": 1.0}]
    with patch("agent_server.subagents.rag.get_pool", return_value=MagicMock()), \
         patch("agent_server.subagents.rag.get_document_store", return_value=_mock_store_with(chunks)), \
         patch("agent_server.subagents.rag.get_settings") as mock_settings:
        mock_settings.return_value.rag_top_k = 5
        from agent_server.subagents.rag import rag_query

        result = await rag_query("test")
    assert len(result) == 1
    assert current_sink() is None


async def test_degraded_paths_do_not_write_sink():
    """空命中 / 后端不可用时不得把降级提示当证据写进池。"""
    sink, token = bind_sink()
    try:
        with patch("agent_server.subagents.rag.get_pool", return_value=MagicMock()), \
             patch("agent_server.subagents.rag.get_document_store", return_value=_mock_store_with([])), \
             patch("agent_server.subagents.rag.get_settings") as mock_settings:
            mock_settings.return_value.rag_top_k = 5
            from agent_server.subagents.rag import rag_query

            await rag_query("test")
        assert sink.rag_chunks == []
        assert sink.is_empty()
    finally:
        reset_sink(token)
