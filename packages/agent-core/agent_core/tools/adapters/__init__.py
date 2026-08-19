# -*- coding: utf-8 -*-
"""
MCP 适配器子包（框架无关内核）。

- ``mcp``：``MCPToolAdapter``（参数化 MCP/SSE 远程工具调用，需要 openai-agents extra ``tools-mcp``）。
"""

from agent_core.tools.adapters.mcp import MCPToolAdapter

__all__ = ["MCPToolAdapter"]
