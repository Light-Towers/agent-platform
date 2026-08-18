# -*- coding: utf-8 -*-
"""框架无关的工具/事件监控外壳（共享可观测性基础设施）。

优化 F：把 deepagents 自研的 ``ToolMonitor`` + ``ConnectionManager`` 下沉到内核，
作为跨子包（deepagents / app / kefu / wenda）共用的监控外壳单一真相源。

设计护栏（遵循 §3 内核零依赖铁律）：
- 核心逻辑仅依赖 stdlib + ``agent_core.logging``，**不硬依赖 fastapi / starlette**。
- ``fastapi.WebSocket`` 仅在 ``ConnectionManager`` 内**惰性 import**（可选依赖），
  无 fastapi 的纯脚本/测试环境可直接用 ``ToolMonitor`` 的回调订阅能力。
- 线程上下文（thread_id）**不耦合宿主** ``api.context``：宿主通过
  ``ToolMonitor.set_context_getter()`` 注入自己的 ContextVar 读取函数，内核默认
  回退到 ``agent_core.tracing`` 的 request_id，保证并发安全且零硬编码依赖。

上报通道：
1. WebSocket：宿主把 ``ConnectionManager`` 实例交给 ``set_websocket_manager``，
   内核按当前 thread_id 推送 monitor_event。
2. 脚本运行时 stream_writer：可选兼容 ``builtins.runtime.stream_writer``（保留 deepagents 旧路径）。
3. 回调订阅：``on(event_type, cb)``，供测试或本地 CLI 直接消费事件。
"""

from __future__ import annotations

import asyncio
import builtins
import datetime
from collections.abc import Callable
from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)


def _default_context_getter() -> str | None:
    """默认上下文读取：回退到 tracing 的 request_id（并发安全，无宿主耦合）。"""
    try:
        from agent_core.tracing import get_request_id

        return get_request_id() or None
    except Exception:
        return None


class ToolMonitor:
    """工具/事件监控器单例。

    跨协程并发安全：thread_id 通过可注入的 context getter（默认 tracing request_id）
    在 emit 时实时读取，不缓存到全局可变状态。
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.websocket_manager = None
            cls._instance._callbacks: dict[str, list[Callable]] = {}
            cls._instance._context_getter: Callable[[], str | None] = _default_context_getter
        return cls._instance

    # -- 配置（宿主注入） -------------------------------------------------
    def set_websocket_manager(self, manager) -> None:
        self.websocket_manager = manager

    def set_context_getter(self, getter: Callable[[], str | None]) -> None:
        """注入宿主的 thread_id 读取函数（如 deepagents 的 ``get_thread_context``）。"""
        if callable(getter):
            self._context_getter = getter

    # -- 核心发送 ---------------------------------------------------------
    def _emit(self, event_type: str, message: str, data: dict[str, Any] | None = None) -> None:
        payload = {
            "type": "monitor_event",
            "event": event_type,
            "message": message,
            "data": data or {},
            "timestamp": datetime.datetime.now().isoformat(),
        }

        # 通道 1：WebSocket
        if self.websocket_manager is not None:
            try:
                thread_id = self._context_getter()
                manager_loop = getattr(self.websocket_manager, "loop", None)
                if thread_id and manager_loop is not None:
                    try:
                        current_loop = asyncio.get_running_loop()
                    except RuntimeError:
                        current_loop = None
                    if current_loop is not None and current_loop == manager_loop:
                        current_loop.create_task(
                            self.websocket_manager.send_to_thread(payload, thread_id)
                        )
                    else:
                        asyncio.run_coroutine_threadsafe(
                            self.websocket_manager.send_to_thread(payload, thread_id),
                            manager_loop,
                        )
            except Exception as e:  # pragma: no cover - 推送失败不应阻断主链路
                logger.warning("WebSocket send failed: %s", e)

        # 通道 2：脚本运行时 stream_writer（可选兼容）
        if hasattr(builtins, "runtime") and hasattr(builtins.runtime, "stream_writer"):
            try:
                builtins.runtime.stream_writer(payload)
            except Exception:
                pass

        logger.debug("[Monitor:%s] %s", event_type, message)

        # 通道 3：回调订阅
        for cb in list(self._callbacks.get(event_type, [])):
            try:
                cb(payload)
            except Exception:
                pass

    # -- 事件上报 API（保持 deepagents 旧签名，零改动调用方） --------------
    def report_tool(self, tool_name: str, args: dict[str, Any] | None = None) -> None:
        self._emit("tool_start", f"开始执行工具: {tool_name}", {"tool_name": tool_name, "args": args})

    def report_assistant(self, assistant_name: str, args: dict[str, Any] | None = None) -> None:
        self._emit(
            "assistant_call",
            f"正在调用助手: {assistant_name}",
            {"assistant_name": assistant_name, "args": args},
        )

    def report_task_result(self, result: str) -> None:
        self._emit("task_result", "任务执行完成", {"result": result})

    def report_session_dir(self, path: str) -> None:
        self._emit("session_created", f"工作目录已创建: {path}", {"path": path})

    def report_error(self, message: str) -> None:
        logger.error("[Monitor:error] %s", message)
        self._emit("error", message)

    def report_circuit(self, state: str, message: str, data: dict[str, Any] | None = None) -> None:
        """上报熔断器状态变化（P3 可观测性）。

        Args:
            state: 目标状态（``open`` / ``half_open`` / ``closed``）。
            message: 人类可读描述。
            data: 附加维度（如 ``agent_name`` / ``failure_count`` / ``threshold``）。
        """
        self._emit("circuit_state_change", message, {"state": state, **(data or {})})

    def report_tool_outcome(
        self,
        tool_name: str,
        outcome: str,
        error_class: str | None = None,
        detail: str = "",
    ) -> None:
        self._emit(
            "tool_outcome",
            f"工具 {tool_name} 结果: {outcome}",
            {"tool_name": tool_name, "outcome": outcome, "error_class": error_class, "detail": detail},
        )

    # -- 回调订阅 ---------------------------------------------------------
    def on(self, event_type: str, callback: Callable) -> None:
        self._callbacks.setdefault(event_type, []).append(callback)

    def off(self, event_type: str, callback: Callable) -> None:
        if event_type in self._callbacks:
            try:
                self._callbacks[event_type].remove(callback)
            except ValueError:
                pass


monitor = ToolMonitor()


class ConnectionManager:
    """WebSocket 连接管理（可选依赖 fastapi，惰性 import）。

    仅负责按 thread_id 维护活动连接 + 向指定 thread 推送 JSON。fastapi.WebSocket
    类型在方法签名内惰性导入，避免无 fastapi 环境 import 失败。

    单例语义：与 ``ToolMonitor`` 一致，模块级 ``manager`` 是推荐共享实例，
    ``ConnectionManager()`` 也返回同一单例，保证跨模块引用的是同一连接表。
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.active_connections = {}
            cls._instance.loop = None
        return cls._instance

    def set_loop(self, loop) -> None:
        self.loop = loop
        monitor.set_websocket_manager(self)
        logger.info("ConnectionManager bound to loop: %s", id(self.loop))

    async def connect(self, websocket, thread_id: str) -> None:
        from fastapi import WebSocket  # 惰性：无 fastapi 时仅 connect 不可用，其余逻辑不影响

        if not isinstance(websocket, WebSocket):
            raise TypeError("ConnectionManager.connect 需要 fastapi.WebSocket（请安装 fastapi）")
        await websocket.accept()
        self.active_connections[thread_id] = websocket
        logger.info("Client connected: %s", thread_id)

    def disconnect(self, websocket, thread_id: str) -> None:
        if thread_id in self.active_connections:
            del self.active_connections[thread_id]
        logger.info("Client disconnected: %s", thread_id)

    async def send_personal_message(self, message: str, websocket) -> None:
        await websocket.send_text(message)

    async def send_to_thread(self, message: dict, thread_id: str) -> None:
        if thread_id in self.active_connections:
            websocket = self.active_connections[thread_id]
            await websocket.send_json(message)


manager = ConnectionManager()


__all__ = [
    "ToolMonitor",
    "monitor",
    "ConnectionManager",
    "manager",
]
