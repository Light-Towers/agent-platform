"""子代理 invoke 契约测试：search / rag / sql / mcp。

mock 外部 HTTP / DB / MCP，测各子代理 invoke 契约 / 错误分支 / 参数校验。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.setenv("SEARCH_API_KEY", "")
    monkeypatch.setenv("DATABASE_URL", "")


async def test_search_web_no_api_key(clean_env):
    """未配置 SEARCH_API_KEY 时返回明确提示。"""
    from agent_server.config import get_settings

    get_settings.cache_clear()
    from agent_server.subagents.search import search_web

    result = await search_web("test query")
    assert len(result) == 1
    assert "未配置" in result[0]


async def test_search_web_with_results(monkeypatch):
    """配置 API key 后正常搜索返回结果。"""
    monkeypatch.setenv("SEARCH_API_KEY", "test-key")
    from agent_server.config import get_settings

    get_settings.cache_clear()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "results": [
            {"title": "Test", "content": "Content", "url": "http://example.com"},
        ]
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        from agent_server.subagents.search import search_web

        result = await search_web("test query")
    assert len(result) == 1
    assert "Test" in result[0]
    get_settings.cache_clear()


async def test_rag_query_backend_unavailable():
    """后端运行时不可用（pgvector 且 pool None）时返回知识库未启用提示。"""
    from agent_runtime.document_store import DocumentStoreUnavailable

    fake_store = MagicMock()
    fake_store.retrieve = AsyncMock(side_effect=DocumentStoreUnavailable("DATABASE_URL 未配置"))
    with patch("agent_server.subagents.rag.get_pool", return_value=None), \
         patch("agent_server.subagents.rag.get_document_store", return_value=fake_store):
        from agent_server.subagents.rag import rag_query

        result = await rag_query("test query")
    assert len(result) == 1
    assert "未启用" in result[0]


async def test_rag_query_backend_not_configured():
    """DOC_BACKEND 未配置完整（工厂返回 None）时降级为可读提示，不 500。"""
    with patch("agent_server.subagents.rag.get_document_store", return_value=None):
        from agent_server.subagents.rag import rag_query

        result = await rag_query("test query")
    assert len(result) == 1
    assert "未启用" in result[0]


async def test_rag_query_with_chunks():
    """有后端且检索到 chunks 时返回格式化证据（经协议，不碰具体后端）。"""
    mock_store = MagicMock()
    mock_chunks = [
        {"source": "doc1", "heading": "标题1", "content": "内容1"},
        {"source": "doc2", "heading": None, "content": "内容2"},
    ]
    mock_store.retrieve = AsyncMock(return_value=mock_chunks)

    with patch("agent_server.subagents.rag.get_pool", return_value=MagicMock()), \
         patch("agent_server.subagents.rag.get_document_store", return_value=mock_store), \
         patch("agent_server.subagents.rag.get_settings") as mock_settings:
        mock_settings.return_value.rag_top_k = 5
        from agent_server.subagents.rag import rag_query

        result = await rag_query("test query")
    assert len(result) == 2
    assert "doc1" in result[0]
    assert "标题1" in result[0]
    assert "无标题" in result[1]


async def test_rag_query_no_chunks():
    """有后端但检索无结果时返回未检索到提示。"""
    mock_store = MagicMock()
    mock_store.retrieve = AsyncMock(return_value=[])

    with patch("agent_server.subagents.rag.get_pool", return_value=MagicMock()), \
         patch("agent_server.subagents.rag.get_document_store", return_value=mock_store), \
         patch("agent_server.subagents.rag.get_settings") as mock_settings:
        mock_settings.return_value.rag_top_k = 5
        from agent_server.subagents.rag import rag_query

        result = await rag_query("test query")
    assert len(result) == 1
    assert "未检索到" in result[0]


async def test_rag_query_passes_knowledge_id_scope():
    """knowledge_id（对话区"知识范围"选择器）必须透传到后端协议。"""
    mock_store = MagicMock()
    mock_store.retrieve = AsyncMock(return_value=[])

    with patch("agent_server.subagents.rag.get_pool", return_value=MagicMock()), \
         patch("agent_server.subagents.rag.get_document_store", return_value=mock_store), \
         patch("agent_server.subagents.rag.get_settings") as mock_settings:
        mock_settings.return_value.rag_top_k = 5
        from agent_server.subagents.rag import rag_query

        await rag_query("test query", "ws1", "kb-123", tenant_id="tenantA")
        await rag_query("test query", tenant_id="tenantA")  # 缺省 = 全部知识库

    scoped = mock_store.retrieve.call_args_list[0]
    assert scoped.kwargs["knowledge_id"] == "kb-123"
    assert scoped.args[3] == "ws1"
    all_libs = mock_store.retrieve.call_args_list[1]
    assert all_libs.kwargs["knowledge_id"] == ""


def test_rag_depends_on_protocol_not_backends():
    """门禁：rag_query 只依赖 DocumentStore 协议与工厂，不 import 具体后端。

    后端可切换的前提是消费方依赖指向接口——谁在 subagents 里 import
    pg_backend / MilvusDocumentStore / store 模块，谁就把切换性打断。
    """
    import inspect

    import agent_server.subagents.rag as rag_mod

    src = inspect.getsource(rag_mod)
    for forbidden in ("pg_backend", "PgVectorDocumentStore", "MilvusDocumentStore", "rag.store"):
        assert forbidden not in src, (
            f"subagents/rag.py 不许 import 具体后端（{forbidden}）："
            "文档检索经 agent_server.rag.backend.get_document_store 工厂取协议"
        )


async def test_mcp_query_none_manager():
    """mcp_manager 为 None 时返回 MCP 未启用。"""
    from agent_server.agent.state import AgentState
    from agent_server.subagents.mcp import mcp_query

    state = AgentState(question="test")
    result = await mcp_query(state, None)
    assert result["evidence"] == ["MCP 未启用"]


async def test_mcp_query_missing_server_id():
    """缺少 server_id 或 tool_name 时返回提示。"""
    from agent_server.agent.state import AgentState
    from agent_server.subagents.mcp import mcp_query

    state = AgentState(question="test", mcp_server="", mcp_tool="")
    result = await mcp_query(state, MagicMock())
    assert "缺少" in result["evidence"][0]


async def test_mcp_query_success():
    """MCP 工具调用成功返回 evidence。"""
    from agent_server.agent.state import AgentState
    from agent_server.subagents.mcp import mcp_query

    state = AgentState(
        question="test",
        mcp_server="srv1",
        mcp_tool="tool1",
        mcp_params={"arg": "val"},
        user_id="user1",
    )
    mock_manager = AsyncMock()
    mock_manager.call_tool = AsyncMock(
        return_value=MagicMock(success=True, evidence=["result1", "result2"])
    )
    result = await mcp_query(state, mock_manager)
    assert result["evidence"] == ["result1", "result2"]


async def test_mcp_query_failure():
    """MCP 工具调用失败返回错误信息。"""
    from agent_server.agent.state import AgentState
    from agent_server.subagents.mcp import mcp_query

    state = AgentState(
        question="test",
        mcp_server="srv1",
        mcp_tool="tool1",
        mcp_params={},
    )
    mock_manager = AsyncMock()
    mock_manager.call_tool = AsyncMock(
        return_value=MagicMock(success=False, evidence=[], error="timeout")
    )
    result = await mcp_query(state, mock_manager)
    assert "失败" in result["evidence"][0]
    assert "timeout" in result["evidence"][0]


async def test_mcp_query_exception():
    """MCP 工具调用异常返回异常提示。"""
    from agent_server.agent.state import AgentState
    from agent_server.subagents.mcp import mcp_query

    state = AgentState(
        question="test",
        mcp_server="srv1",
        mcp_tool="tool1",
        mcp_params={},
    )
    mock_manager = AsyncMock()
    mock_manager.call_tool = AsyncMock(side_effect=RuntimeError("connection refused"))
    result = await mcp_query(state, mock_manager)
    assert "异常" in result["evidence"][0]


async def test_sql_query_basic():
    """sql_query 改调 nl2sql /api/query 并格式化为证据（A 方案 Stage ③）。"""
    resp_payload = {
        "answer": "上月销售额 12345 元",
        "sql": "SELECT SUM(amount) FROM orders",
        "error": None,
        "empty_result_reason": None,
    }

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return resp_payload

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, **kwargs):
            assert url.endswith("/api/query"), f"应打 nl2sql /api/query，实际 {url}"
            assert json["query"] == "test query"
            return _Resp()

    with patch("httpx.AsyncClient", return_value=_Client()), \
         patch("agent_server.subagents.sql_agent.get_settings") as mock_settings:
        mock_settings.return_value.nl2sql_service_url = "http://nl2sql:8000"
        mock_settings.return_value.default_tenant_id = ""
        from agent_server.subagents.sql_agent import sql_query

        result = await sql_query("test query")
    assert result == ["执行的 SQL：SELECT SUM(amount) FROM orders\n上月销售额 12345 元"]


async def test_sql_query_unconfigured_returns_explicit_notice():
    """NL2SQL_SERVICE_URL 未配置：明确提示而非静默空结果（同 search.py 降级契约）。"""
    with patch("agent_server.subagents.sql_agent.get_settings") as mock_settings:
        mock_settings.return_value.nl2sql_service_url = ""
        from agent_server.subagents.sql_agent import sql_query

        result = await sql_query("test query")
    assert result == ["问数服务未配置（NL2SQL_SERVICE_URL 为空）"]


async def test_sql_query_http_error_is_classified():
    """上游不可达：错误分类进证据，不把异常抛给图节点。"""
    import httpx

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, **kwargs):
            raise httpx.ConnectError("connection refused")

    with patch("httpx.AsyncClient", return_value=_Client()), \
         patch("agent_server.subagents.sql_agent.get_settings") as mock_settings:
        mock_settings.return_value.nl2sql_service_url = "http://nl2sql:8000"
        mock_settings.return_value.default_tenant_id = ""
        from agent_server.subagents.sql_agent import sql_query

        result = await sql_query("test query")
    assert "不可达" in result[0]
