# -*- coding: utf-8 -*-
"""框架无关的工具/事件监控外壳（共享可观测性基础设施）。

优化 F：把 deepagents 自研的 ``ToolMonitor`` + ``ConnectionManager`` 下沉到内核，
作为跨子包（deepagents / app / kefu / wenda）共用的监控外壳单一真相源。

WS-4（统一事件出口）：事件流改经 ``agent_core.events.EventBus`` 扇出——
WebSocket / 回调订阅 / 旧 builtins.runtime 通道全部实现为 EventSink，逐 sink
异常隔离；新增出口（OTel span 事件、测试采集器等）只需 ``bus.add_sink(...)``。

设计护栏（遵循 §3 内核零依赖铁律）：
- 核心逻辑仅依赖 stdlib + ``agent_core.logging`` / ``agent_core.events``，
  **不硬依赖 fastapi / starlette**。
- ``fastapi.WebSocket`` 仅在 ``ConnectionManager`` 内**惰性 import**（可选依赖），
  无 fastapi 的纯脚本/测试环境可直接用 ``ToolMonitor`` 的回调订阅能力。
- 线程上下文（thread_id）**不耦合宿主** ``api.context``：宿主通过
  ``ToolMonitor.set_context_getter()`` 注入自己的 ContextVar 读取函数，内核默认
  回退到 ``agent_core.tracing`` 的 request_id，保证并发安全且零硬编码依赖。

上报通道（均为 EventSink 实现）：
1. WebSocket：宿主把 ``ConnectionManager`` 实例交给 ``set_websocket_manager``，
   内核按当前 thread_id 推送 monitor_event（``WebSocketSink``）。
2. 脚本运行时 stream_writer：``LegacyStreamSink`` 可选兼容
   ``builtins.runtime.stream_writer``（保留 deepagents 旧路径，弃用警告一次）。
3. 回调订阅：``on(event_type, cb)``（``CallbackSink``），供测试或本地 CLI 直接消费事件。
4. OTel span 事件：``OTelSpanSink`` 把业务事件挂到当前活跃 span（OTel 未启用时
   静默 no-op，零开销）。

单例治理（WS-4）：模块级 ``monitor`` 仍是默认共享单例（``ToolMonitor()`` 返回它），
但显式传 ``bus`` 时构造**独立实例**——测试一律用注入式实例，互不污染。
"""

from __future__ import annotations

import asyncio
import datetime
from collections.abc import Callable
from typing import Any

from agent_core.events import CallbackSink, EventBus, LegacyStreamSink, OTelSpanSink
from agent_core.logging import get_logger

logger = get_logger(__name__)


def _default_context_getter() -> str | None:
    """默认上下文读取：回退到 tracing 的 request_id（并发安全，无宿主耦合）。"""
    try:
        from agent_core.tracing import get_request_id

        return get_request_id() or None
    except Exception:
        return None


class WebSocketSink:
    """WebSocket 出口：按当前 thread_id 把事件推送给 ConnectionManager。

    跨事件循环安全：manager 绑定 loop 与当前 loop 不一致时经
    ``run_coroutine_threadsafe`` 投递；未绑定 loop / 无 thread_id 时静默跳过。
    """

    def __init__(self, monitor: "ToolMonitor") -> None:
        self._monitor = monitor

    def emit(self, event: dict[str, Any]) -> None:
        manager = self._monitor.websocket_manager
        if manager is None:
            return
        thread_id = self._monitor._context_getter()
        manager_loop = getattr(manager, "loop", None)
        if not thread_id or manager_loop is None:
            return
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        if current_loop is not None and current_loop == manager_loop:
            current_loop.create_task(manager.send_to_thread(event, thread_id))
        else:
            asyncio.run_coroutine_threadsafe(
                manager.send_to_thread(event, thread_id), manager_loop
            )


class ToolMonitor:
    """工具/事件监控器：事件经 EventBus 扇出到各 EventSink。

    跨协程并发安全：thread_id 通过可注入的 context getter（默认 tracing request_id）
    在 emit 时实时读取，不缓存到全局可变状态。

    构造语义（WS-4）：``ToolMonitor()`` 返回模块单例（兼容既有调用方）；
    ``ToolMonitor(bus=EventBus())`` 构造独立实例供测试/隔离场景注入使用。
    """

    _instance = None

    def __new__(cls, bus: EventBus | None = None):
        if bus is None and cls._instance is not None:
            return cls._instance
        instance = super().__new__(cls)
        instance._init(bus)
        if bus is None:
            cls._instance = instance
        return instance

    def _init(self, bus: EventBus | None) -> None:
        self.bus = bus or EventBus()
        self.websocket_manager = None
        self._context_getter: Callable[[], str | None] = _default_context_getter
        self._callback_sink = CallbackSink()
        self._ws_sink = WebSocketSink(self)
        self._legacy_sink = LegacyStreamSink()
        self._otel_sink = OTelSpanSink()
        self.bus.add_sink(self._callback_sink)
        self.bus.add_sink(self._ws_sink)
        self.bus.add_sink(self._legacy_sink)
        self.bus.add_sink(self._otel_sink)

    def __init__(self, bus: EventBus | None = None) -> None:
        # 单例语义下 __init__ 会被重复调用，实际初始化在 __new__/_init 完成
        pass

    # -- 兼容属性：旧代码直读 monitor._callbacks ---------------------------
    @property
    def _callbacks(self) -> dict[str, list[Callable]]:
        return self._callback_sink._callbacks  # noqa: SLF001 兼容旧测试/调用方

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
        # WS-4：统一经 EventBus 扇出（WebSocket / 回调 / legacy 通道均为 sink，
        # 逐 sink 异常隔离，单通道故障不影响其余出口）
        self.bus.emit(payload)
        logger.debug("[Monitor:%s] %s", event_type, message)

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

    # -- 回调订阅（委托 CallbackSink）--------------------------------------
    def on(self, event_type: str, callback: Callable) -> None:
        self._callback_sink.on(event_type, callback)

    def off(self, event_type: str, callback: Callable) -> None:
        self._callback_sink.off(event_type, callback)


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
    "WebSocketSink",
    "monitor",
    "ConnectionManager",
    "manager",
]
