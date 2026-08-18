# -*- coding: utf-8 -*-
"""deepagents WS 监控外壳 —— 兼容 re-export 层（优化 F 下沉）。

维护历史公开 API：``monitor`` / ``manager`` / ``ToolMonitor`` / ``ConnectionManager``，
以及 ``build_thread_id`` / ``extract_thread_id_from_scope`` 等 deepagents 私有的线程 id 工具。

实现已下沉到 ``agent_core.monitor``（框架无关内核），这里只做：
1. 兼容 re-export，保证 deepagents 内 70+ 处 ``from api.monitor import monitor`` 零改动；
2. 把 deepagents 的 ``get_thread_context`` 注入内核，恢复"每请求 thread_id"语义；
3. 保留 deepagents 独有的 thread_id 推导工具（WebSocket scope 解析）。
"""

from __future__ import annotations

from typing import Any

from agent_core.monitor import (
    ConnectionManager,
    ToolMonitor,
)
from agent_core.monitor import (
    manager as _manager,
)
from agent_core.monitor import (
    monitor as _monitor,
)

# 注入 deepagents 的 thread 上下文读取函数，恢复并发安全的 thread_id 语义。
try:
    from api.context import get_thread_context

    _monitor.set_context_getter(get_thread_context)
except Exception:  # pragma: no cover
    pass

# 公开兼容符号
monitor = _monitor
manager = _manager
ToolMonitor = ToolMonitor
ConnectionManager = ConnectionManager


# -- deepagents 私有 thread_id 工具（保留，供 server.py / ws 端点使用） -----
def build_thread_id(user_id: str, sid: str) -> str:
    return f"user-{user_id}-session-{sid}"


def extract_thread_id_from_scope(scope: dict[str, Any]) -> str | None:
    """从 WebSocket/HTTP scope 的 query 中解析 thread_id。"""
    query = scope.get("query_string", b"").decode("utf-8")
    for pair in query.split("&"):
        if not pair:
            continue
        k, _, v = pair.partition("=")
        if k == "thread_id":
            return v or None
    return None


__all__ = [
    "monitor",
    "manager",
    "ToolMonitor",
    "ConnectionManager",
    "build_thread_id",
    "extract_thread_id_from_scope",
]
