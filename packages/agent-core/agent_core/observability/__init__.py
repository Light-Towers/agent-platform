# -*- coding: utf-8 -*-
"""工具可观测性（方案 v3 批 1 kernel）。

- :mod:`tool_result`：``ToolResult`` / ``ToolOutcome`` 协议——stdlib 零依赖；
- :func:`observe_tool`：StructuredTool 观测包装器入口——langchain 依赖经
  函数级懒导入隔离（模式同 :mod:`agent_core.llm.fallback_lc`），其余内核
  模块不得 import :mod:`tool_wrap_lc`。

单一实现原则：federation ``tool_registry`` 与 agent_server ``SkillRegistry``
均为本模块的**装配点**，不得各自实现包装逻辑（方案 v3 W1）。
"""

from typing import Any

from agent_core.observability.tool_result import ToolOutcome, ToolResult

__all__ = ["ToolOutcome", "ToolResult", "observe_tool"]


def observe_tool(tool: Any, *, display_names: dict[str, str] | None = None, monitor: Any | None = None) -> Any:
    """包装 langchain StructuredTool：双路（sync/async）观测，元数据原样保留。

    Args:
        tool: ``@tool`` 产物（StructuredTool 实例）。
        display_names: ``tool.name -> 展示名`` 映射（兼容现中文人工名）。
        monitor: 显式注入 ToolMonitor（测试隔离）；缺省全局共享单例。
    """
    from agent_core.observability.tool_wrap_lc import observe_tool_lc

    return observe_tool_lc(tool, display_names=display_names, monitor=monitor)
