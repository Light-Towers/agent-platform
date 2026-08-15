# -*- coding: utf-8 -*-
"""
工具协议（框架无关内核，源自 zhiku fanout / MCP 节点抽象）。

定义宿主无关的 ``Tool`` 协议：任何实现了 ``name`` 与 ``invoke(state) -> dict`` 的对象
都可作为可被注册表管理、被 guard 包裹的工具。

框架无关：本模块**零第三方依赖**，仅 stdlib + typing。
"""

from typing import Any, Dict, Protocol, runtime_checkable


@runtime_checkable
class Tool(Protocol):
    """可被注册 / guard 包裹的工具协议。"""

    name: str

    def invoke(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """执行工具，返回对上游状态的部分更新 dict（失败也应返回 {}，由 guard 兜底）。

        :param state: 上游传入的状态（如检索图 state）。
        :return: 状态更新 dict。
        """
        ...


__all__ = ["Tool"]
