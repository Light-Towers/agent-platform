"""ToolObservedMiddleware 单测（方案 v3 §4 第二装配点）。

事件契约与 federation observe_tool 一致：tool_start(args 摘要) +
tool_outcome(outcome/error_class/duration_ms)；ToolResult 语义透传；
外抛 re-raise。独立 ToolMonitor 实例 + EventBus 采集，不污染全局单例。
"""

import pytest
from agent_core.events import EventBus
from agent_core.monitor import ToolMonitor
from agent_core.observability import ToolOutcome, ToolResult

from agent_runtime.skills.middleware import ToolObservedMiddleware


def _make_mw_and_events(display_names=None) -> tuple[ToolObservedMiddleware, list[dict]]:
    captured: list[dict] = []
    m = ToolMonitor(bus=EventBus())
    m.on("tool_start", captured.append)
    m.on("tool_outcome", captured.append)
    mw = ToolObservedMiddleware(monitor=m, display_names=display_names)
    return mw, captured


async def test_success_emits_start_and_outcome():
    mw, events = _make_mw_and_events()

    async def call_next(name, kwargs):
        return "ok"

    result = await mw.around("search", {"q": "x"}, call_next)

    assert result == "ok"
    kinds = [e["event"] for e in events]
    assert kinds == ["tool_start", "tool_outcome"]
    assert events[0]["data"]["args"]["q"] == "'x'"
    assert events[1]["data"]["outcome"] == "success"
    assert events[1]["data"]["duration_ms"] is not None


async def test_tool_result_outcome_passthrough():
    mw, events = _make_mw_and_events()

    async def call_next(name, kwargs):
        return ToolResult(text="无结果", outcome=ToolOutcome.EMPTY, detail="q: x")

    result = await mw.around("rag", {"q": "x"}, call_next)

    # LLM 可见文本 = ToolResult.text
    assert result == "无结果"
    outcomes = [e for e in events if e["event"] == "tool_outcome"]
    assert outcomes[0]["data"]["outcome"] == "empty"
    assert outcomes[0]["data"]["detail"] == "q: x"


async def test_exception_recorded_and_reraised():
    mw, events = _make_mw_and_events()

    async def call_next(name, kwargs):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await mw.around("sql", {"query": "select"}, call_next)

    outcomes = [e for e in events if e["event"] == "tool_outcome"]
    assert outcomes[0]["data"]["outcome"] == "exception"
    assert outcomes[0]["data"]["error_class"] == "RuntimeError"


def test_display_name_mapping():
    mw, events = _make_mw_and_events(display_names={"search": "网络搜索工具"})

    async def call_next(name, kwargs):
        return "ok"

    # 直接驱动 around（同步驱动 async 事件断言已由上方用例覆盖，这里只看名字）
    import asyncio

    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        mw.around("search", {}, call_next)
    )
    assert events[0]["data"]["tool_name"] == "网络搜索工具"
