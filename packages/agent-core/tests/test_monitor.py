# -*- coding: utf-8 -*-
"""agent_core.monitor 框架无关外壳单测（无 fastapi 依赖）。"""

import pytest

from agent_core.monitor import (
    ConnectionManager,
    ToolMonitor,
    monitor,
    manager,
)


def test_singleton():
    assert ToolMonitor() is monitor
    assert ConnectionManager() is manager


def test_callback_subscription():
    events = []

    def cb(payload):
        events.append(payload)

    monitor.on("tool_start", cb)
    try:
        monitor.report_tool("search", {"q": "x"})
        assert len(events) == 1
        assert events[0]["event"] == "tool_start"
        assert events[0]["data"]["tool_name"] == "search"
        assert events[0]["type"] == "monitor_event"
    finally:
        monitor.off("tool_start", cb)


def test_report_assistant_and_outcome():
    events = []

    monitor.on("assistant_call", lambda p: events.append(p))
    monitor.on("tool_outcome", lambda p: events.append(p))
    try:
        monitor.report_assistant("mysql_agent", {"sql": "select 1"})
        monitor.report_tool_outcome("mysql_agent", "success")
        assert [e["event"] for e in events] == ["assistant_call", "tool_outcome"]
    finally:
        # 清理所有该类型回调
        for et in ("assistant_call", "tool_outcome"):
            for cb in list(monitor._callbacks.get(et, [])):
                monitor.off(et, cb)


def test_context_getter_injection(monkeypatch):
    captured = {}

    def fake_getter():
        return "thread-xyz"

    monitor.set_context_getter(fake_getter)
    try:
        # 不接 websocket_manager，仅验证 context getter 可被注入且不抛错
        monitor.report_task_result("done")
        captured["ok"] = True
    finally:
        # 恢复默认
        from agent_core.monitor import _default_context_getter

        monitor.set_context_getter(_default_context_getter)
    assert captured.get("ok")


def test_connection_manager_no_fastapi_loop_safe():
    cm = ConnectionManager()
    # 未绑定 loop 时不应崩溃
    assert cm.active_connections == {}
    cm.disconnect(object(), "no-thread")
