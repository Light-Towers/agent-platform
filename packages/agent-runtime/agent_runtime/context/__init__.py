"""Context Pipeline（Plan-F）：统一上下文组装管线。

设计原则（对齐 external review）：不推倒重来，把已有的 tokenizer / compact /
ContextManager 三个部件串成统一管线，全部落在 agent-runtime 层，agent_server 与
federation 共用。

- ``budget``：分层 token 预算（比例可配，未用完余量按优先级回流）；
- ``assembler``：ContextAssembler 唯一组装入口（collect → rank → budget → compress → assemble）；
- ``compact``：上下文压缩（由 agent_server 下沉，去 langchain 化，dict 消息）；
- ``tool_result``：Tool Result 压缩 + 外置（head/tail + 关键字段 + ref handle）；
- ``memory_gate``：记忆召回门控（去重 / 冲突消解 / 预算内取 top）；
- ``skill_context``：Skill-local context slicing（父 context 只传切片，嵌套 token 加法化）。
"""

from __future__ import annotations

from agent_runtime.context.assembler import (
    AssemblyBlock,
    AssemblyReport,
    ContextAssembler,
)
from agent_runtime.context.budget import ContextBudget, Layer
from agent_runtime.context.compact import compact_messages, estimate_tokens, should_compact
from agent_runtime.context.memory_gate import MemoryGate
from agent_runtime.context.skill_context import SkillInvocationContext, slice_skill_context
from agent_runtime.context.tool_result import ToolResultCompressor, compress_result, read_tool_result

__all__ = [
    "AssemblyBlock",
    "AssemblyReport",
    "ContextAssembler",
    "ContextBudget",
    "Layer",
    "MemoryGate",
    "SkillInvocationContext",
    "ToolResultCompressor",
    "compact_messages",
    "compress_result",
    "estimate_tokens",
    "read_tool_result",
    "should_compact",
    "slice_skill_context",
]