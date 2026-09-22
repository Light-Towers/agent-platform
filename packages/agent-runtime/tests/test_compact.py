"""compact_messages 单元测试：上下文压缩 + 降级。"""

from __future__ import annotations

import pytest

from agent_runtime.context.compact import compact_messages, estimate_tokens, should_compact


def test_estimate_tokens_basic():
    msgs = [{"role": "user", "content": "hello world"}]
    assert estimate_tokens(msgs) > 0


def test_should_compact_false_when_few_messages():
    msgs = [{"role": "user", "content": "x"}]
    assert should_compact(msgs, threshold_tokens=1) is False


def test_should_compact_false_when_under_threshold():
    msgs = [{"role": "user", "content": "short"}] * 10
    assert should_compact(msgs, threshold_tokens=999_999) is False


def test_should_compact_true_when_over_threshold():
    msgs = [{"role": "user", "content": "x" * 200}] * 20
    assert should_compact(msgs, threshold_tokens=10) is True


@pytest.mark.asyncio
async def test_compact_messages_preserves_recent():
    msgs = [{"role": "user", "content": f"msg {i}"} for i in range(10)]

    class FakeLLM:
        async def ainvoke(self, messages):
            return type("R", (), {"content": "summary"})()

    compacted, err = await compact_messages(msgs, FakeLLM())
    assert err is None
    assert len(compacted) == 5
    assert compacted[0]["role"] == "system"
    assert "[上下文摘要]" in compacted[0]["content"]
    assert compacted[-1]["content"] == "msg 9"


@pytest.mark.asyncio
async def test_compact_messages_no_op_when_few():
    msgs = [{"role": "user", "content": "hi"}]

    class FakeLLM:
        async def ainvoke(self, messages):
            return type("R", (), {"content": "summary"})()

    compacted, err = await compact_messages(msgs, FakeLLM())
    assert err is None
    assert compacted == msgs


@pytest.mark.asyncio
async def test_compact_messages_degrades_on_llm_failure():
    msgs = [{"role": "user", "content": f"msg {i}"} for i in range(10)]

    class FailingLLM:
        async def ainvoke(self, messages):
            raise RuntimeError("LLM unavailable")

    compacted, err = await compact_messages(msgs, FailingLLM())
    assert err is not None
    assert "COMPACTION_FAILED" in err
    assert compacted == msgs
