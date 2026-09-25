"""agent_core.observability.observe_tool 批 1 kernel 单测（方案 v3 §6）。

覆盖（方案验收 §6 对应项）：
- 成功路径（str 返回）→ tool_start + tool_outcome(success) + duration_ms；
- ToolResult 返回 → outcome 语义透传（empty/degraded）且 LLM 文本 = result.text；
- 外抛 → tool_outcome(exception, error_class=类型名) 且异常原样 re-raise；
- sync / async 双路；
- 元数据保留：name/description/args_schema 逐字段相等；
- display_name 映射生效；
- args 摘要截断（512 字符）。

langchain_core 为可选依赖：importorskip 守卫（缺 SDK 环境自动 skip，非失败）。
"""

from __future__ import annotations

import pytest

pytest.importorskip("langchain_core")

from langchain_core.tools import StructuredTool

from agent_core.events import EventBus
from agent_core.monitor import ToolMonitor
from agent_core.observability import ToolOutcome, ToolResult, observe_tool


def _make_monitor() -> tuple[ToolMonitor, list[dict]]:
    """独立 ToolMonitor 实例 + 事件采集器（互不污染全局单例）。"""
    captured: list[dict] = []
    m = ToolMonitor(bus=EventBus())
    m.on("tool_start", captured.append)
    m.on("tool_outcome", captured.append)
    return m, captured


def _make_sync_tool() -> StructuredTool:
    def add(a: int, b: int) -> str:
        """add two ints."""
        return str(a + b)

    return StructuredTool.from_function(func=add, name="add", description="add two ints")


def test_sync_success_emits_start_and_outcome():
    m, events = _make_monitor()
    wrapped = observe_tool(_make_sync_tool(), display_names={"add": "加法工具"}, monitor=m)

    result = wrapped.invoke({"a": 1, "b": 2})

    assert result == "3"
    starts = [e for e in events if e["event"] == "tool_start"]
    outcomes = [e for e in events if e["event"] == "tool_outcome"]
    assert len(starts) == 1 and len(outcomes) == 1
    # display_name 映射生效（C3）
    assert starts[0]["data"]["tool_name"] == "加法工具"
    assert outcomes[0]["data"]["tool_name"] == "加法工具"
    assert outcomes[0]["data"]["outcome"] == "success"
    assert outcomes[0]["data"]["duration_ms"] is not None
    # args 摘要存在（截断由 _summarize 保证，此处仅断言字段在）
    assert "a" in starts[0]["data"]["args"]


def test_tool_result_outcome_passthrough_and_text_forwarding():
    m, events = _make_monitor()

    def fetch(table: str) -> ToolResult:
        """fetch rows."""
        return ToolResult(text="表 x 无数据", outcome=ToolOutcome.EMPTY, detail=f"table: {table}")

    tool = StructuredTool.from_function(func=fetch, name="fetch", description="fetch")
    wrapped = observe_tool(tool, monitor=m)

    result = wrapped.invoke({"table": "x"})

    # LLM 可见文本 = ToolResult.text（非 str(result) 之外的对象泄漏）
    assert result == "表 x 无数据"
    outcomes = [e for e in events if e["event"] == "tool_outcome"]
    assert len(outcomes) == 1
    assert outcomes[0]["data"]["outcome"] == "empty"
    assert outcomes[0]["data"]["detail"] == "table: x"


async def test_async_success_and_metadata_preserved():
    m, events = _make_monitor()

    async def asearch(q: str) -> str:
        """async search."""
        return f"hits:{q}"

    tool = StructuredTool.from_function(coroutine=asearch, name="asearch", description="async search")
    wrapped = observe_tool(tool, monitor=m)

    # 元数据逐字段相等（W4）
    assert wrapped.name == tool.name
    assert wrapped.description == tool.description
    assert wrapped.args == tool.args

    result = await wrapped.ainvoke({"q": "booth"})
    assert result == "hits:booth"
    outcomes = [e for e in events if e["event"] == "tool_outcome"]
    assert len(outcomes) == 1
    assert outcomes[0]["data"]["outcome"] == "success"


async def test_async_exception_recorded_and_reraised():
    m, events = _make_monitor()

    async def boom(q: str) -> str:
        """boom."""
        raise RuntimeError("db down")

    tool = StructuredTool.from_function(coroutine=boom, name="boom", description="d")
    wrapped = observe_tool(tool, monitor=m)

    with pytest.raises(RuntimeError, match="db down"):
        await wrapped.ainvoke({"q": "x"})

    outcomes = [e for e in events if e["event"] == "tool_outcome"]
    assert len(outcomes) == 1
    assert outcomes[0]["data"]["outcome"] == "exception"
    assert outcomes[0]["data"]["error_class"] == "RuntimeError"


def test_tool_result_degraded_with_error_class():
    m, events = _make_monitor()

    def flaky() -> str:
        """flaky."""
        return ToolResult(
            text="服务降级，请稍后重试",
            outcome=ToolOutcome.DEGRADED,
            detail="服务不健康",
            error_class="HTTP429",
        )

    tool = StructuredTool.from_function(func=flaky, name="flaky", description="d")
    wrapped = observe_tool(tool, monitor=m)

    assert wrapped.invoke({}) == "服务降级，请稍后重试"
    outcomes = [e for e in events if e["event"] == "tool_outcome"]
    assert outcomes[0]["data"]["outcome"] == "degraded"
    assert outcomes[0]["data"]["error_class"] == "HTTP429"


def test_args_summary_truncated(monkeypatch):

    m, events = _make_monitor()
    big = "x" * 2000

    def echo(payload: str) -> str:
        """echo."""
        return payload

    tool = StructuredTool.from_function(func=echo, name="echo", description="d")
    wrapped = observe_tool(tool, monitor=m)
    wrapped.invoke({"payload": big})

    starts = [e for e in events if e["event"] == "tool_start"]
    arg_repr = starts[0]["data"]["args"]["payload"]
    # 单值 repr 截断（512 + 截断标记）
    assert len(arg_repr) <= 512 + len("…<truncated>")
    assert arg_repr.endswith("…<truncated>")
