# -*- coding: utf-8 -*-
"""
工具注册表（框架无关内核，源自 zhiku fanout 的通道登记抽象）。

``ToolRegistry`` 管理工具条目及其元数据（``enabled`` / ``timeout_s``），供
``guarded_invoke`` / ``wrap_tool`` 读取执行策略。

框架无关：本模块**零第三方依赖**，仅 stdlib。
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agent_core.logging import get_logger
from agent_core.tools.base import Tool

logger = get_logger(__name__)


@dataclass
class ToolEntry:
    """注册表中的工具条目（含执行策略元数据）。"""

    name: str
    tool: Any  # 实现 Tool 协议（invoke(state)->dict）
    enabled: bool = True
    timeout_s: float = 3.0


class ToolRegistry:
    """工具注册表：register / get / list，含 enabled / timeout_s 元数据。"""

    def __init__(self) -> None:
        self._entries: Dict[str, ToolEntry] = {}

    def register(
        self,
        name: str,
        tool: Any,
        *,
        enabled: bool = True,
        timeout_s: float = 3.0,
    ) -> ToolEntry:
        """注册一个工具（同名覆盖）。"""
        entry = ToolEntry(name=name, tool=tool, enabled=enabled, timeout_s=timeout_s)
        self._entries[name] = entry
        logger.info("已注册工具: %s enabled=%s timeout_s=%s", name, enabled, timeout_s)
        return entry

    def get(self, name: str) -> Optional[ToolEntry]:
        """按名获取条目（不存在返回 None）。"""
        return self._entries.get(name)

    def list(self) -> List[ToolEntry]:
        """列出全部条目。"""
        return list(self._entries.values())

    def enabled_names(self) -> List[str]:
        """列出当前启用（enabled=True）的工具名。"""
        return [e.name for e in self._entries.values() if e.enabled]


__all__ = ["ToolEntry", "ToolRegistry"]
