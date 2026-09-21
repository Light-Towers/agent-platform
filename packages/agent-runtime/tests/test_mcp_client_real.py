"""MCP client 真实 SDK 接入测试：_reduce_result / _invoke_tool / close_all。"""

from __future__ import annotations

import pytest

from agent_runtime.circuit_breaker import CircuitBreaker
from agent_runtime.mcp_client import MCPClientManager, _MCPConnection
from agent_runtime.schemas import McpServerConfig


def _make_manager() -> MCPClientManager:
    config = McpServerConfig(
        server_id="test-server",
        transport="sse",
        endpoint="http://localhost:9999",
        tool_allowlist=["weather"],
        enabled=True,
    )
    return MCPClientManager(server_configs=[config])


def _make_conn() -> _MCPConnection:
    config = McpServerConfig(
        server_id="test-server",
        transport="sse",
        endpoint="http://localhost:9999",
        tool_allowlist=["weather"],
        enabled=True,
    )
    return _MCPConnection(config, CircuitBreaker())


# ---- _reduce_result 测试 ----


def test_reduce_result_handles_call_tool_result():
    """_reduce_result 处理 MCP SDK CallToolResult（含 content 列表）。"""
    from mcp.types import CallToolResult, TextContent

    manager = _make_manager()
    result = CallToolResult(content=[TextContent(text="晴天 25°C")])
    evidence = manager._reduce_result("srv", "weather", result)
    assert len(evidence) == 1
    assert "晴天 25°C" in evidence[0]
    assert "[MCP: srv/weather]" in evidence[0]


def test_reduce_result_handles_multiple_content_items():
    """_reduce_result 处理多个 content item。"""
    from mcp.types import CallToolResult, TextContent

    manager = _make_manager()
    result = CallToolResult(content=[TextContent(text="a"), TextContent(text="b")])
    evidence = manager._reduce_result("srv", "tool", result)
    assert len(evidence) == 2
    assert "a" in evidence[0]
    assert "b" in evidence[1]


def test_reduce_result_raises_on_is_error():
    """_reduce_result 在 is_error=True 时 raise RuntimeError。"""
    from mcp.types import CallToolResult, TextContent

    manager = _make_manager()
    result = CallToolResult(content=[TextContent(text="boom")], is_error=True)
    with pytest.raises(RuntimeError, match="returned error"):
        manager._reduce_result("srv", "tool", result)


def test_reduce_result_truncates_long_content():
    """_reduce_result 对超长 content 截断。"""
    from mcp.types import CallToolResult, TextContent

    manager = _make_manager()
    long_text = "x" * 1000
    result = CallToolResult(content=[TextContent(text=long_text)])
    evidence = manager._reduce_result("srv", "tool", result)
    assert len(evidence[0]) < 600
    assert "..." in evidence[0]


def test_reduce_result_handles_dict_backward_compat():
    """_reduce_result 仍兼容 dict 类型（旧 mock 路径）。"""
    manager = _make_manager()
    result = {"tool": "weather", "result": "sunny"}
    evidence = manager._reduce_result("srv", "weather", result)
    assert len(evidence) == 1
    assert "sunny" in evidence[0]


def test_reduce_result_handles_plain_string():
    """_reduce_result 兼容纯字符串。"""
    manager = _make_manager()
    evidence = manager._reduce_result("srv", "tool", "hello")
    assert len(evidence) == 1
    assert "hello" in evidence[0]


# ---- _invoke_tool 测试 ----


@pytest.mark.asyncio
async def test_invoke_tool_calls_session_call_tool():
    """_invoke_tool 经 session.call_tool 发起真实调用。"""
    manager = _make_manager()
    conn = _make_conn()

    call_args = {}

    class FakeSession:
        async def call_tool(self, name, arguments):
            call_args["name"] = name
            call_args["arguments"] = arguments
            from mcp.types import CallToolResult, TextContent
            return CallToolResult(content=[TextContent(text="result")])

    conn.session = FakeSession()
    result = await manager._invoke_tool(conn, "weather", {"city": "北京"})
    assert call_args["name"] == "weather"
    assert call_args["arguments"] == {"city": "北京"}
    assert hasattr(result, "content")


@pytest.mark.asyncio
async def test_invoke_tool_without_sdk_raises():
    """_MCP_AVAILABLE=False 时 _invoke_tool raise。"""
    import agent_runtime.mcp_client as mod

    original = mod._MCP_AVAILABLE
    mod._MCP_AVAILABLE = False
    try:
        manager = _make_manager()
        conn = _make_conn()
        conn.session = None
        with pytest.raises(RuntimeError, match="MCP SDK not installed"):
            await manager._invoke_tool(conn, "weather", {})
    finally:
        mod._MCP_AVAILABLE = original


# ---- _discover_tools 测试 ----


@pytest.mark.asyncio
async def test_discover_tools_calls_list_tools():
    """_discover_tools 经 session.list_tools 提取工具名。"""
    manager = _make_manager()

    class FakeTool:
        def __init__(self, name):
            self.name = name

    class FakeListResult:
        tools = [FakeTool("weather"), FakeTool("calc")]

    class FakeSession:
        async def list_tools(self):
            return FakeListResult()

    tools = await manager._discover_tools(FakeSession())
    assert tools == ["weather", "calc"]


# ---- close_all 测试 ----


@pytest.mark.asyncio
async def test_close_all_closes_exit_stack():
    """close_all 调用 _exit_stack.aclose()。"""
    manager = _make_manager()
    conn = _make_conn()
    conn.available = True

    closed = False

    class FakeStack:
        async def aclose(self):
            nonlocal closed
            closed = True

    conn._exit_stack = FakeStack()
    manager._connections["test-server"] = conn

    await manager.close_all()
    assert closed is True
    assert len(manager._connections) == 0


@pytest.mark.asyncio
async def test_close_all_without_exit_stack():
    """close_all 在 _exit_stack=None 时不报错。"""
    manager = _make_manager()
    conn = _make_conn()
    conn.available = True
    conn._exit_stack = None
    manager._connections["test-server"] = conn

    await manager.close_all()
    assert len(manager._connections) == 0


# ---- call_tool 集成（经 _invoke_tool mock） ----


@pytest.mark.asyncio
async def test_call_tool_with_is_error_returns_failure():
    """call_tool 在工具返回 is_error=True 时返回 McpToolResult(success=False)。"""
    from mcp.types import CallToolResult, TextContent

    manager = _make_manager()
    conn = _make_conn()
    conn.available = True
    conn.session = None
    manager._connections["test-server"] = conn

    async def fake_invoke(conn, tool_name, params):
        return CallToolResult(content=[TextContent(text="error")], is_error=True)

    manager._invoke_tool = fake_invoke

    result = await manager.call_tool("test-server", "weather", {}, "caller")
    assert result.success is False
    assert result.error == "TOOL_RETURNED_ERROR"


@pytest.mark.asyncio
async def test_call_tool_with_text_content_returns_evidence():
    """call_tool 在工具返回 TextContent 时提取为 evidence。"""
    from mcp.types import CallToolResult, TextContent

    manager = _make_manager()
    conn = _make_conn()
    conn.available = True
    conn.session = None
    manager._connections["test-server"] = conn

    async def fake_invoke(conn, tool_name, params):
        return CallToolResult(content=[TextContent(text="晴天 25°C")])

    manager._invoke_tool = fake_invoke

    result = await manager.call_tool("test-server", "weather", {}, "caller")
    assert result.success is True
    assert len(result.evidence) == 1
    assert "晴天 25°C" in result.evidence[0]
