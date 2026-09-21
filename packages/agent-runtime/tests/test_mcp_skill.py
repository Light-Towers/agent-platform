"""MCP Skill 注册测试：register_mcp_skills 把 MCP 工具注册为 Skill。"""

from __future__ import annotations

import pytest

from agent_runtime.mcp_client import MCPClientManager
from agent_runtime.schemas import McpServerConfig, McpToolResult
from agent_runtime.skills.mcp import register_mcp_skills
from agent_runtime.skills.registry import SkillKind, SkillRegistry


def _make_manager_with_tools() -> MCPClientManager:
    """构造已连接的 MCPClientManager（mock，不经真实 SDK）。"""
    config = McpServerConfig(
        server_id="test-server",
        transport="sse",
        endpoint="http://localhost:9999",
        tool_allowlist=["weather", "calc"],
        enabled=True,
    )
    manager = MCPClientManager(server_configs=[config])
    # 手动注入连接状态（绕过 connect_all，不需要真实 MCP SDK）
    from agent_runtime.circuit_breaker import CircuitBreaker
    from agent_runtime.mcp_client import _MCPConnection

    conn = _MCPConnection(config, CircuitBreaker())
    conn.tools = ["weather", "calc"]
    conn.available = True
    conn.session = {"endpoint": config.endpoint}
    manager._connections["test-server"] = conn
    return manager


@pytest.mark.asyncio
async def test_register_mcp_skills_registers_all_tools():
    manager = _make_manager_with_tools()
    registry = SkillRegistry()
    count = register_mcp_skills(manager, registry)
    assert count == 2
    assert "mcp.test-server.weather" in registry
    assert "mcp.test-server.calc" in registry


def test_register_mcp_skills_skill_kind_and_metadata():
    manager = _make_manager_with_tools()
    registry = SkillRegistry()
    register_mcp_skills(manager, registry)
    skill = registry.get("mcp.test-server.weather")
    assert skill.kind == SkillKind.REMOTE
    assert skill.metadata["source"] == "mcp"
    assert skill.metadata["server_id"] == "test-server"
    assert skill.metadata["tool_name"] == "weather"


def test_register_mcp_skills_permissions_from_allowlist():
    manager = _make_manager_with_tools()
    registry = SkillRegistry()
    register_mcp_skills(manager, registry)
    skill = registry.get("mcp.test-server.weather")
    assert "mcp:test-server" in skill.permissions


def test_register_mcp_skills_skips_existing():
    manager = _make_manager_with_tools()
    registry = SkillRegistry()
    register_mcp_skills(manager, registry)
    # 二次注册应跳过已存在的
    count = register_mcp_skills(manager, registry)
    assert count == 0


def test_register_mcp_skills_skips_unavailable():
    manager = _make_manager_with_tools()
    manager._connections["test-server"].available = False
    registry = SkillRegistry()
    count = register_mcp_skills(manager, registry)
    assert count == 0


@pytest.mark.asyncio
async def test_mcp_skill_executor_calls_manager(monkeypatch):
    manager = _make_manager_with_tools()
    registry = SkillRegistry()
    register_mcp_skills(manager, registry)

    # mock call_tool 返回成功
    async def fake_call_tool(server_id, tool_name, params, caller):
        assert server_id == "test-server"
        assert tool_name == "weather"
        assert params == {"city": "北京"}
        return McpToolResult(success=True, evidence=["晴天 25°C"], duration_ms=10)

    monkeypatch.setattr(manager, "call_tool", fake_call_tool)

    result = await registry.execute("mcp.test-server.weather", city="北京")
    assert result == ["晴天 25°C"]


@pytest.mark.asyncio
async def test_mcp_skill_executor_raises_on_failure(monkeypatch):
    manager = _make_manager_with_tools()
    registry = SkillRegistry()
    register_mcp_skills(manager, registry)

    async def failing_call_tool(server_id, tool_name, params, caller):
        return McpToolResult(success=False, error="CONNECTION_TIMEOUT", duration_ms=5000)

    monkeypatch.setattr(manager, "call_tool", failing_call_tool)

    with pytest.raises(RuntimeError, match="CONNECTION_TIMEOUT"):
        await registry.execute("mcp.test-server.weather", city="上海")


def test_register_mcp_skills_discoverable():
    """注册后 MCP 工具可经 discover() 发现。"""
    manager = _make_manager_with_tools()
    registry = SkillRegistry()
    register_mcp_skills(manager, registry)
    results = registry.discover("weather", top_k=10)
    names = [s.name for s in results]
    assert "mcp.test-server.weather" in names
