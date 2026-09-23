"""MCP Skill 注册：把 MCPClientManager 发现的工具自动注册为 Skill。

架构契约：MCP server 的每个工具编译为一个 ``SkillKind.REMOTE`` Skill，
注册到 SkillRegistry 后可经 ``discover()`` 发现、``delegate()`` 调用——
与 Function/Agent/Workflow Skill 同构，Planner 无需感知 MCP 协议细节。

Skill 命名：``mcp.{server_id}.{tool_name}``（三段式，避免跨 server 工具名冲突）。
Skill executor：调用 ``MCPClientManager.call_tool(server_id, tool_name, params, caller)``，
返回 ``McpToolResult``，executor 提取 ``evidence`` 列表返回。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agent_runtime.skills.registry import ExecutionBoundary, Skill, SkillKind

if TYPE_CHECKING:
    from agent_runtime.mcp_client import MCPClientManager
    from agent_runtime.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


def register_mcp_skills(
    manager: "MCPClientManager",
    registry: "SkillRegistry",
    *,
    caller: str = "skill_registry",
) -> int:
    """把 MCPClientManager 发现的所有工具注册为 Skill。

    遍历 ``manager._connections`` 中每个可用连接的工具列表，
    为每个 ``(server_id, tool_name)`` 创建一个 ``SkillKind.REMOTE`` Skill。

    :param manager: 已 ``connect_all()`` 的 MCPClientManager。
    :param registry: 目标 SkillRegistry。
    :param caller: 审计 caller 标识（默认 "skill_registry"）。
    :return: 成功注册的 Skill 数量（已存在的跳过，不计入）。
    """
    count = 0
    for server_id, conn in manager._connections.items():
        if not conn.available:
            continue
        for tool_name in conn.tools:
            skill_name = f"mcp.{server_id}.{tool_name}"
            if skill_name in registry:
                continue
            skill = _make_mcp_skill(
                server_id=server_id,
                tool_name=tool_name,
                manager=manager,
                caller=caller,
                allowlist=conn.config.tool_allowlist,
            )
            try:
                registry.register(skill)
                count += 1
            except Exception:  # noqa: BLE001
                logger.warning("MCP Skill 注册失败: %s", skill_name, exc_info=True)
    return count


def _make_mcp_skill(
    *,
    server_id: str,
    tool_name: str,
    manager: "MCPClientManager",
    caller: str,
    allowlist: list[str],
) -> Skill:
    """为单个 MCP 工具创建 Skill。"""
    skill_name = f"mcp.{server_id}.{tool_name}"
    description = f"MCP 工具: {server_id}/{tool_name}"
    permissions = frozenset({f"mcp:{server_id}"}) if allowlist else frozenset()

    async def execute(**kwargs: object) -> object:
        result = await manager.call_tool(server_id, tool_name, kwargs, caller)
        if not result.success:
            raise RuntimeError(f"MCP 调用失败: {result.error}")
        return result.evidence

    return Skill(
        name=skill_name,
        description=description,
        kind=SkillKind.REMOTE,
        executor=execute,
        execution_boundary=ExecutionBoundary.REMOTE,
        metadata={"source": "mcp", "server_id": server_id, "tool_name": tool_name},
        permissions=permissions,
    )


__all__ = ["register_mcp_skills"]
