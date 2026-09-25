# -*- coding: utf-8 -*-
"""
工具注册表子包（框架无关内核，源自 zhiku fanout / MCP 节点抽象）。

- ``base``：``Tool`` 协议（实现 ``name`` + ``invoke(state)->dict`` 即可被管理）；
- ``registry``：``ToolRegistry``（register / get / list，含 enabled / timeout_s）；
- ``guarded``：``guarded_invoke`` / ``wrap_tool``（逐路超时隔离 + 失败降级，去除 retrieval_cfg 依赖）；
- ``adapters.mcp``：``MCPToolAdapter``（参数化 MCP/SSE 调用，需要 openai-agents extra ``tools-mcp``）。

框架无关：base / registry / guarded 仅 stdlib + agent_core.logging/tracing；
mcp 适配器需 openai-agents（懒导入降级）。
"""

from agent_core.tools.base import Tool
from agent_core.tools.guarded import guarded_invoke, wrap_tool
from agent_core.tools.registry import ToolEntry, ToolRegistry

__all__ = [
    "Tool",
    "ToolEntry",
    "ToolRegistry",
    "guarded_invoke",
    "wrap_tool",
]
