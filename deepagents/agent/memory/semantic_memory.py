# -*- coding: utf-8 -*-
"""语义长期记忆门面（deepagents 薄封装）。

实现已统一收口到 agent-core（agent_core.memory.semantic），此处仅保持
``agent.memory.semantic_memory`` 路径兼容，委托内核实现。请勿在此重复逻辑。

调用方应优先直接 ``from agent_core.memory import recall_memories, remember_memory``。
"""

from agent_core.memory import (
    get_default_backend,
    get_semantic_memory,
    recall_memories,
    remember_memory,
    semantic_memory_enabled,
)

__all__ = [
    "semantic_memory_enabled",
    "get_default_backend",
    "get_semantic_memory",
    "recall_memories",
    "remember_memory",
]
