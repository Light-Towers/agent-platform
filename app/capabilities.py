"""app 侧 Capability Registry 装配（Plan-F Phase 1）。

注册 search/rag/sql/mcp 四个进程内能力；graph 节点经注册表统一执行——
能力注册/发现收敛到单一入口，Planner（Phase 2）可经此调用任意能力。

注册表为模块级惰性单例（幂等），进程生命周期内复用。
"""

from __future__ import annotations

from typing import Any

from agent_runtime.capabilities.function import as_function_capability
from agent_runtime.capabilities.registry import CapabilityRegistry
from agent_runtime.mcp_client import MCPClientManager
from app.agent.state import AgentState
from app.subagents.mcp import mcp_query
from app.subagents.rag import rag_query
from app.subagents.search import search_web
from app.subagents.sql_agent import sql_query

_registry: CapabilityRegistry | None = None


async def _mcp_execute(state: AgentState, mcp_manager: MCPClientManager | None) -> dict[str, Any]:
    """mcp 能力适配：签名依赖 state + manager（与 search/rag/sql 的 query 形态不同）。"""
    return await mcp_query(state, mcp_manager)


def build_registry() -> CapabilityRegistry:
    """构建 app 能力注册表（幂等；重复调用返回新实例，供测试隔离）。"""
    registry = CapabilityRegistry()
    registry.register(
        as_function_capability("search", "联网搜索（Tavily）：返回证据字符串列表", search_web)
    )
    registry.register(
        as_function_capability(
            "rag", "知识库混合检索：按 workspace 过滤，返回证据字符串列表", rag_query
        )
    )
    registry.register(
        as_function_capability(
            "sql", "SQL 查询：text-to-SQL 管线，返回证据字符串列表", sql_query
        )
    )
    registry.register(
        as_function_capability(
            "mcp",
            "MCP 工具调用：调用外部工具并归约为 evidence（依赖 state + manager）",
            _mcp_execute,
        )
    )
    return registry


def get_registry() -> CapabilityRegistry:
    """进程级单例注册表。"""
    global _registry
    if _registry is None:
        _registry = build_registry()
    return _registry
