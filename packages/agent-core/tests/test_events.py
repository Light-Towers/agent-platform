# -*- coding: utf-8 -*-
"""WS-4：EventBus 统一事件出口单测（扇出 / 异常隔离 / 注入式实例）。"""

from __future__ import annotations

from agent_core.events import (
    CallbackSink,
    EventBus,
    EventSink,
    LegacyStreamSink,
    OTelSpanSink,
)
from agent_core.monitor import ToolMonitor


class _Collector:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)


class _BoomSink:
    def emit(self, event):
        raise RuntimeError("sink broken")


def test_bus_fanout_to_multiple_sinks():
    bus = EventBus()
    a, b = _Collector(), _Collector()
    bus.add_sink(a)
    bus.add_sink(b)
    bus.emit({"event": "tool_start", "data": {}})
    assert len(a.events) == 1 and len(b.events) == 1


def test_bus_sink_failure_isolated_and_counted():
    bus = EventBus()
    good = _Collector()
    bus.add_sink(_BoomSink())
    bus.add_sink(good)
    bus.emit({"event": "x"})  # 不因坏 sink 抛出
    assert len(good.events) == 1
    assert bus.dropped == 1


def test_bus_add_remove_sink():
    bus = EventBus()
    sink = _Collector()
    bus.add_sink(sink)
    bus.add_sink(sink)  # 去重
    assert len(bus.sinks) == 1
    bus.remove_sink(sink)
    bus.emit({"event": "x"})
    assert sink.events == []


def test_callback_sink_dispatches_by_event_type():
    sink = CallbackSink()
    got = []
    sink.on("tool_start", lambda e: got.append(e["event"]))
    sink.emit({"event": "tool_start"})
    sink.emit({"event": "other"})
    assert got == ["tool_start"]


def test_callback_sink_subscriber_failure_isolated():
    sink = CallbackSink()
    got = []
    sink.on("x", lambda e: (_ for _ in ()).throw(RuntimeError("boom")))
    sink.on("x", lambda e: got.append(1))
    # 订阅方抛错不影响其余回调……（CallbackSink.emit 逐回调隔离）
    sink.emit({"event": "x"})
    assert got == [1]


def test_legacy_stream_sink_noop_without_builtins_runtime():
    sink = LegacyStreamSink()
    sink.emit({"event": "x"})  # 无 builtins.runtime 时静默跳过，不抛


def test_otel_span_sink_noop_without_active_span():
    """WS-4：无活跃 span（或 OTel 未安装）时静默跳过，绝不抛。"""
    sink = OTelSpanSink()
    sink.emit({"event": "tool_start", "message": "m", "data": {"k": "v"}})


def test_otel_span_sink_writes_to_recording_span(monkeypatch):
    """有记录中的活跃 span 时，事件写为 span event。"""
    recorded = []

    class _FakeSpan:
        def is_recording(self):
            return True

        def add_event(self, name, attributes=None):
            recorded.append((name, attributes))

    class _FakeOtelTrace:
        @staticmethod
        def get_current_span():
            return _FakeSpan()

    import sys
    import types

    fake_mod = types.ModuleType("opentelemetry")
    fake_mod.trace = _FakeOtelTrace
    monkeypatch.setitem(sys.modules, "opentelemetry", fake_mod)

    sink = OTelSpanSink()
    sink.emit({"event": "tool_start", "message": "开工", "data": {"tool_name": "search"}})
    assert recorded[0][0] == "tool_start"
    assert recorded[0][1]["tool_name"] == "search"
    assert recorded[0][1]["monitor.message"] == "开工"


def test_monitor_injected_instance_isolated():
    """注入式实例（WS-4 去单例污染）：独立 bus，不与模块单例互相影响。"""
    from agent_core.monitor import monitor

    bus = EventBus()
    collector = _Collector()
    bus.add_sink(collector)
    isolated = ToolMonitor(bus=bus)
    assert isolated is not monitor

    isolated.report_tool("search")
    assert len(collector.events) == 1

    # 单例上的事件不进注入实例的 bus
    before = len(collector.events)
    monitor.report_tool("other")
    assert len(collector.events) == before


def test_monitor_default_singleton_contract():
    from agent_core.monitor import monitor

    assert ToolMonitor() is monitor
    assert isinstance(monitor.bus, EventBus)


def test_event_sink_protocol_runtime_checkable():
    assert isinstance(_Collector(), EventSink)
