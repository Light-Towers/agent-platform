# -*- coding: utf-8 -*-
"""统一事件出口（WS-4）：EventSink 协议 + EventBus 多 sink 扇出。

背景：此前可观测性有三套互不相通的机制——OTel tracing、Langfuse callbacks、
``monitor.ToolMonitor``（内含 WebSocket / builtins.runtime / 回调三通道）。本模块
定义统一事件出口契约：**业务事件经 EventBus 扇出到多个 EventSink**，每个 sink
异常隔离，单 sink 故障不影响其余出口。

分工声明（与 agent_runtime.tracing 的边界）：
- Langfuse / OTel span 级 LLM trace 仍走各自接线（宿主注入凭据）；
- EventBus 承载业务事件（tool_start / circuit_state_change / monitor_event 等），
  OTel 侧如需消费可注册一个 sink 把事件挂到当前 span。

§3 内核护栏：仅 stdlib，零第三方依赖；sink 失败绝不向事件源回抛。
"""

from __future__ import annotations

import threading
import warnings
from typing import Any, Protocol, runtime_checkable

from agent_core.logging import get_logger

logger = get_logger(__name__)


@runtime_checkable
class EventSink(Protocol):
    """事件出口契约：接收一条事件 dict（monitor_event 形态）。"""

    def emit(self, event: dict[str, Any]) -> None:
        """处理一条事件；实现方应自行保证不抛异常或接受被 EventBus 隔离。"""
        ...


class EventBus:
    """多 sink 事件总线：扇出 + 逐 sink 异常隔离 + 失败计数。

    并发安全：sink 注册表受锁保护；emit 期间对快照迭代，允许运行时增删 sink。
    """

    def __init__(self) -> None:
        self._sinks: list[EventSink] = []
        self._lock = threading.Lock()
        self.dropped: int = 0  # sink 异常导致的事件丢弃计数（观测用）

    def add_sink(self, sink: EventSink) -> None:
        with self._lock:
            if sink not in self._sinks:
                self._sinks.append(sink)

    def remove_sink(self, sink: EventSink) -> None:
        with self._lock:
            try:
                self._sinks.remove(sink)
            except ValueError:
                pass

    @property
    def sinks(self) -> list[EventSink]:
        with self._lock:
            return list(self._sinks)

    def emit(self, event: dict[str, Any]) -> None:
        """扇出事件到全部 sink；单个 sink 异常隔离（计数 + 日志），绝不回抛。"""
        for sink in self.sinks:
            try:
                sink.emit(event)
            except Exception as e:  # noqa: BLE001 —— sink 故障不影响主链路
                self.dropped += 1
                logger.warning("EventSink %r 处理事件失败（已隔离）: %s", sink, e)


class LegacyStreamSink:
    """兼容旧 ``builtins.runtime.stream_writer`` 通道（保留一个小版本）。

    deepagents 脚本运行时的隐式全局路径；WS-4 起改为显式注册的 sink，
    首次实际命中时触发一次 DeprecationWarning，提示宿主迁移到显式 sink。
    """

    _warned = False

    def emit(self, event: dict[str, Any]) -> None:
        import builtins

        writer = getattr(getattr(builtins, "runtime", None), "stream_writer", None)
        if writer is None:
            return
        if not LegacyStreamSink._warned:
            LegacyStreamSink._warned = True
            warnings.warn(
                "builtins.runtime.stream_writer 通道已弃用，请注册显式 EventSink（WS-4）",
                DeprecationWarning,
                stacklevel=2,
            )
        writer(event)


class OTelSpanSink:
    """OTel span 事件出口（WS-4）：把业务事件挂到当前活跃 span 上。

    opentelemetry 为可选依赖（懒导入）：SDK 不可用 / 无活跃 span /
    span 不在记录中 → 静默跳过，绝不抛异常。与 Langfuse 的分工：
    Langfuse 管 LLM trace，本 sink 承载业务事件（monitor_event）。
    """

    def emit(self, event: dict[str, Any]) -> None:
        try:
            from opentelemetry import trace as otel_trace
        except Exception:  # noqa: BLE001 - OTel 未安装时降级 no-op
            return
        try:
            span = otel_trace.get_current_span()
        except Exception:  # noqa: BLE001
            return
        if span is None or not span.is_recording():
            return
        attrs = {k: str(v) for k, v in (event.get("data") or {}).items()}
        attrs["monitor.message"] = str(event.get("message", ""))
        span.add_event(str(event.get("event", "monitor_event")), attrs)


class CallbackSink:
    """按 event_type 的回调订阅 sink（承接 ToolMonitor.on/off 语义）。"""

    def __init__(self) -> None:
        self._callbacks: dict[str, list[Any]] = {}
        self._lock = threading.Lock()

    def on(self, event_type: str, callback: Any) -> None:
        with self._lock:
            self._callbacks.setdefault(event_type, []).append(callback)

    def off(self, event_type: str, callback: Any) -> None:
        with self._lock:
            if event_type in self._callbacks:
                try:
                    self._callbacks[event_type].remove(callback)
                except ValueError:
                    pass

    def callbacks(self, event_type: str) -> list[Any]:
        with self._lock:
            return list(self._callbacks.get(event_type, []))

    def emit(self, event: dict[str, Any]) -> None:
        event_type = event.get("event", "")
        for cb in self.callbacks(event_type):
            try:
                cb(event)
            except Exception:  # noqa: BLE001 —— 订阅方异常隔离
                logger.warning("事件回调执行失败（已隔离）: event=%s", event_type)


__all__ = ["EventSink", "EventBus", "LegacyStreamSink", "OTelSpanSink", "CallbackSink"]
