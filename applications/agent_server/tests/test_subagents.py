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


async def test_rag_query_no_pool():
    """pool 为 None 时返回知识库未启用提示。"""
    with patch("agent_runtime.db.get_pool", return_value=None):
        from agent_server.subagents.rag import rag_query

        result = await rag_query("test query")
    assert len(result) == 1
    assert "未启用" in result[0]


async def test_rag_query_with_chunks(monkeypatch):
    """有 pool 且检索到 chunks 时返回格式化证据。"""
    mock_pool = MagicMock()
    mock_chunks = [
        {"source": "doc1", "heading": "标题1", "content": "内容1"},
        {"source": "doc2", "heading": None, "content": "内容2"},
    ]

    with patch("agent_server.subagents.rag.get_pool", return_value=mock_pool), \
         patch("agent_server.subagents.rag.retrieve_chunks", new_callable=AsyncMock, return_value=mock_chunks), \
         patch("agent_server.subagents.rag.get_settings") as mock_settings:
        mock_settings.return_value.rag_top_k = 5
        from agent_server.subagents.rag import rag_query

        result = await rag_query("test query")
    assert len(result) == 2
    assert "doc1" in result[0]
    assert "标题1" in result[0]
    assert "无标题" in result[1]


async def test_rag_query_no_chunks(monkeypatch):
    """有 pool 但检索无结果时返回未检索到提示。"""
    mock_pool = MagicMock()
    with patch("agent_server.subagents.rag.get_pool", return_value=mock_pool), \
         patch("agent_server.subagents.rag.retrieve_chunks", new_callable=AsyncMock, return_value=[]), \
         patch("agent_server.subagents.rag.get_settings") as mock_settings:
        mock_settings.return_value.rag_top_k = 5
        from agent_server.subagents.rag import rag_query

        result = await rag_query("test query")
    assert len(result) == 1
    assert "未检索到" in result[0]


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
    """sql_query 返回格式化结果。"""
    mock_pool = MagicMock()
    mock_payload = {"sql": "SELECT 1", "rows": [{"a": 1}], "error": None}

    with patch("agent_runtime.db.get_pool", return_value=mock_pool), \
         patch("agent_server.subagents.sql_agent.text_to_sql", new_callable=AsyncMock, return_value=mock_payload), \
         patch("agent_server.subagents.sql_agent.format_result", return_value="formatted result"):
        from agent_server.subagents.sql_agent import sql_query

        result = await sql_query("test query")
    assert result == ["formatted result"]
