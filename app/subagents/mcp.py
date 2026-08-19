"""MCP 图节点：路由至 mcp 时调用外部工具，结果归约为 evidence。"""

import logging

from agent_runtime.mcp_client import MCPClientManager

from app.agent.state import AgentState

logger = logging.getLogger(__name__)


async def mcp_query(state: AgentState, mcp_manager: MCPClientManager | None) -> dict:
    """MCP 能力节点：调用工具并返回 evidence。"""
    if mcp_manager is None:
        return {"evidence": ["MCP 未启用"]}

    server_id = state.mcp_server
    tool_name = state.mcp_tool
    params = state.mcp_params
    caller = state.user_id

    if not server_id or not tool_name:
        return {"evidence": ["MCP 路由缺少 server_id 或 tool_name"]}

    try:
        result = await mcp_manager.call_tool(server_id, tool_name, params, caller)
    except Exception:
        logger.warning("mcp_query failed", exc_info=True)
        return {"evidence": ["MCP 工具调用异常"]}

    if result.success:
        return {"evidence": result.evidence}
    return {"evidence": [f"MCP 工具调用失败：{result.error}"]}
