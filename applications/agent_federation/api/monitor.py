# -*- coding: utf-8 -*-
"""agent_federation WS 监控外壳 —— 兼容 re-export 层（优化 F 下沉）。

维护历史公开 API：``monitor`` / ``manager`` / ``ToolMonitor`` / ``ConnectionManager``。

实现已下沉到 ``agent_core.monitor``（框架无关内核），这里只做：
1. 兼容 re-export，保证 agent_federation 内 70+ 处 ``from api.monitor import monitor`` 零改动；
2. 把 agent_federation 的 ``get_thread_context`` 注入内核，恢复"每请求 thread_id"语义。

G16 清理（2026-10-23）：``build_thread_id`` / ``extract_thread_id_from_scope``
两符号已删——全仓零调用（联邦真实链路走 ``api/server.py`` 的 ``resolve_thread_id``
→ 内核 ``resolve_thread_identity``，``tenant-`` 形态），且 ``user-<uid>-session-<sid>``
形态与已退役的旧凭据摘要前缀同名易误导。判定其数据形态仍见
``scripts/migrate_thread_identity.py`` 的人工核实分支。
"""

from __future__ import annotations

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

# 注入 agent_federation 的 thread 上下文读取函数，恢复并发安全的 thread_id 语义。
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



__all__ = [
    "monitor",
    "manager",
    "ToolMonitor",
    "ConnectionManager",
]
