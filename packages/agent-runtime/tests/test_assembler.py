"""ContextAssembler 单元测试：collect → rank → budget → compress → assemble。"""

from __future__ import annotations

import pytest

from agent_runtime.context.assembler import ContextAssembler
from agent_runtime.context.budget import ContextBudget


def _make_assembler(window=128_000, llm=None) -> ContextAssembler:
    return ContextAssembler(ContextBudget(model_window=window), llm=llm)


@pytest.mark.asyncio
async def test_assemble_basic_system_and_user():
    a = _make_assembler()
    messages, report = await a.assemble(
        user_message="你好",
        system_prompt="你是助手",
    )
    assert report.messages_count >= 2
    roles = [m["role"] for m in messages]
    assert "system" in roles
    assert "user" in roles


@pytest.mark.asyncio
async def test_assemble_preserves_system_first():
    a = _make_assembler()
    messages, _ = await a.assemble(
        user_message="问题",
        system_prompt="系统提示",
    )
    assert messages[0]["role"] == "system"
    assert "系统提示" in messages[0]["content"]


@pytest.mark.asyncio
async def test_assemble_with_conversation():
    a = _make_assembler()
    conv = [
        {"role": "user", "content": "之前的问题"},
        {"role": "assistant", "content": "之前的回答"},
    ]
    messages, report = await a.assemble(
        user_message="新问题",
        conversation=conv,
    )
    assert report.messages_count >= 3


@pytest.mark.asyncio
async def test_assemble_with_tool_results():
    a = _make_assembler()
    messages, report = await a.assemble(
        user_message="查数据",
        tool_results=["结果1", "结果2"],
    )
    contents = [m["content"] for m in messages]
    assert any("结果1" in c for c in contents)
    assert any("结果2" in c for c in contents)


@pytest.mark.asyncio
async def test_assemble_with_snapshot():
    a = _make_assembler()
    snapshot = {
        "task": {"goal": "分析数据", "completed_steps": ["step1"], "pending": ["step2"]},
        "execution": {"outputs": {"key": "val"}, "errors": {}},
    }
    messages, report = await a.assemble(
        user_message="继续",
        snapshot=snapshot,
    )
    contents = [m["content"] for m in messages]
    assert any("分析数据" in c for c in contents)
    assert any("执行状态" in c for c in contents)


@pytest.mark.asyncio
async def test_assemble_with_memories():
    a = _make_assembler()
    messages, report = await a.assemble(
        user_message="回忆",
        memories=["之前做过X", "也做过Y"],
    )
    contents = [m["content"] for m in messages]
    assert any("之前做过X" in c for c in contents)


@pytest.mark.asyncio
async def test_assemble_with_tool_defs():
    a = _make_assembler()
    messages, _ = await a.assemble(
        user_message="用什么工具",
        tool_defs=[{"name": "search", "description": "搜索"}],
    )
    contents = [m["content"] for m in messages]
    assert any("search" in c and "搜索" in c for c in contents)


@pytest.mark.asyncio
async def test_assemble_conversation_truncate_without_llm():
    a = _make_assembler(window=500, llm=None)
    conv = [{"role": "user", "content": f"消息 {i} " * 20} for i in range(20)]
    messages, report = await a.assemble(
        user_message="新问题",
        conversation=conv,
    )
    assert report.total_tokens <= report.input_budget or len(report.actions) > 0


@pytest.mark.asyncio
async def test_assemble_conversation_compact_with_llm():
    class FakeLLM:
        async def ainvoke(self, msgs):
            return type("R", (), {"content": "摘要内容"})()

    a = _make_assembler(window=500, llm=FakeLLM())
    conv = [{"role": "user", "content": f"消息 {i} " * 20} for i in range(20)]
    messages, report = await a.assemble(
        user_message="新问题",
        conversation=conv,
    )
    assert any(a.get("action") == "compacted" for a in report.actions) or report.total_tokens <= report.input_budget


@pytest.mark.asyncio
async def test_assemble_report_to_dict():
    a = _make_assembler()
    _, report = await a.assemble(user_message="x", system_prompt="y")
    d = report.to_dict()
    assert "model_window" in d
    assert "input_budget" in d
    assert "total_tokens" in d
    assert "layers" in d
    assert "messages_count" in d


@pytest.mark.asyncio
async def test_assemble_conversation_only_no_compaction():
    a = _make_assembler()
    msgs = [{"role": "user", "content": "短消息"}]
    result, report = await a.assemble_conversation_only(messages=msgs)
    assert result is None


@pytest.mark.asyncio
async def test_assemble_conversation_only_with_compaction():
    class FakeLLM:
        async def ainvoke(self, msgs):
            return type("R", (), {"content": "压缩摘要"})()

    a = _make_assembler(window=500, llm=FakeLLM())
    msgs = [{"role": "user", "content": f"长消息 {i} " * 30} for i in range(20)]
    result, report = await a.assemble_conversation_only(messages=msgs)
    if result is not None:
        assert result[0]["role"] == "system"
        assert "压缩摘要" in result[0]["content"]


@pytest.mark.asyncio
async def test_assemble_empty_inputs():
    a = _make_assembler()
    messages, report = await a.assemble()
    assert report.messages_count == 0
    assert messages == []
