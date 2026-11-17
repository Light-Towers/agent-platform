"""MCP Capability 注册：把 MCPClientManager 发现的工具自动注册为 Capability。

架构契约：MCP server 的每个工具编译为一个 ``CapabilityKind.REMOTE`` Capability，
注册到 CapabilityRegistry 后可经 ``discover()`` 发现、``delegate()`` 调用——
与 Function/Agent/Workflow Capability 同构，Planner 无需感知 MCP 协议细节。

Capability 命名：``mcp.{server_id}.{tool_name}``（三段式，避免跨 server 工具名冲突）。
Capability executor：调用 ``MCPClientManager.call_tool(server_id, tool_name, params, caller)``，
返回 ``McpToolResult``，executor 提取 ``evidence`` 列表返回。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agent_runtime.capabilities.registry import Capability, CapabilityKind, ExecutionBoundary

if TYPE_CHECKING:
    from agent_runtime.capabilities.registry import CapabilityRegistry
    from agent_runtime.mcp_client import MCPClientManager

logger = logging.getLogger(__name__)


def register_mcp_capabilities(
    manager: "MCPClientManager",
    registry: "CapabilityRegistry",
    *,
    caller: str = "capability_registry",
) -> int:
    """把 MCPClientManager 发现的所有工具注册为 Capability。

    遍历 ``manager._connections`` 中每个可用连接的工具列表，
    为每个 ``(server_id, tool_name)`` 创建一个 ``CapabilityKind.REMOTE`` Capability。

    :param manager: 已 ``connect_all()`` 的 MCPClientManager。
    :param registry: 目标 CapabilityRegistry。
    :param caller: 审计 caller 标识（默认 "capability_registry"）。
    :return: 成功注册的 Capability 数量（已存在的跳过，不计入）。
    """
    count = 0
    for server_id, conn in manager._connections.items():
        if not conn.available:
            continue
        for tool_name in conn.tools:
            capability_name = f"mcp.{server_id}.{tool_name}"
            if capability_name in registry:
                continue
            capability = _make_mcp_capability(
                server_id=server_id,
                tool_name=tool_name,
                manager=manager,
                caller=caller,
                allowlist=conn.config.tool_allowlist,
            )
            try:
                registry.register(capability)
                count += 1
            except Exception:
                logger.warning("MCP Capability 注册失败: %s", capability_name, exc_info=True)
    return count


def _make_mcp_capability(
    *,
    server_id: str,
    tool_name: str,
    manager: "MCPClientManager",
    caller: str,
    allowlist: list[str],
) -> Capability:
    """为单个 MCP 工具创建 Capability。"""
    capability_name = f"mcp.{server_id}.{tool_name}"
    description = f"MCP 工具: {server_id}/{tool_name}"
    permissions = frozenset({f"mcp:{server_id}"}) if allowlist else frozenset()

    async def execute(**kwargs: object) -> object:
        result = await manager.call_tool(server_id, tool_name, kwargs, caller)
        if not result.success:
            raise RuntimeError(f"MCP 调用失败: {result.error}")
        return result.evidence

    return Capability(
        name=capability_name,
        description=description,
        kind=CapabilityKind.REMOTE,
        executor=execute,
        execution_boundary=ExecutionBoundary.REMOTE,
        metadata={"source": "mcp", "server_id": server_id, "tool_name": tool_name},
        permissions=permissions,
    )


__all__ = ["register_mcp_capabilities"]
