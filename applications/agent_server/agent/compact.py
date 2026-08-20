"""上下文压缩（Plan-F Context Pipeline）：已下沉至 agent-runtime。

本文件保留为**兼容 shim**：原实现（langchain SystemMessage 形态）已迁移至
``agent_runtime.context.compact``（dict 消息形态，agent_server/federation 共用），
此处 re-export 保持既有 import 路径不破。新代码请直接 import agent-runtime 版本。
"""

from __future__ import annotations

from agent_runtime.context.compact import (
    _KEEP_RECENT,
    _SUMMARY_PROMPT,
    _msg_content,
    _msg_role,
    compact_messages,
    estimate_tokens,
    should_compact,
)

__all__ = [
    "_KEEP_RECENT",
    "_SUMMARY_PROMPT",
    "compact_messages",
    "estimate_tokens",
    "should_compact",
]