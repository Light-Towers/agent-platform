"""上下文压缩 compact 测试。"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agent.compact import (
    _KEEP_RECENT,
    compact_messages,
    estimate_tokens,
    should_compact,
)


class _MockLLM:
    def __init__(self, response: str = "摘要内容"):
        self._response = response
        self.invoke_count = 0

    async def ainvoke(self, messages, **kwargs):
        self.invoke_count += 1
        return AIMessage(content=self._response)


class _FailingLLM:
    async def ainvoke(self, messages, **kwargs):
        raise RuntimeError("LLM 不可用")


def test_estimate_tokens_empty():
    assert estimate_tokens([]) == 0


def test_estimate_tokens_basic():
    msgs = [HumanMessage(content="你好世界"), AIMessage(content="你好")]
    tokens = estimate_tokens(msgs)
    assert tokens > 0
    assert tokens == int((4 + 2) / 1.5)


def test_should_compact_below_threshold():
    msgs = [HumanMessage(content="短消息")]
    assert not should_compact(msgs, 1000)


def test_should_compact_too_few_messages():
    msgs = [HumanMessage(content="x" * 10000) for _ in range(_KEEP_RECENT)]
    assert not should_compact(msgs, 1)


def test_should_compact_triggers():
    msgs = [HumanMessage(content="x" * 200) for _ in range(10)]
    assert should_compact(msgs, 100)


@pytest.mark.asyncio
async def test_compact_messages_success():
    msgs = [HumanMessage(content=f"问题{i}") for i in range(8)] + [AIMessage(content=f"回答{i}") for i in range(8)]
    llm = _MockLLM("这是摘要")
    compacted, err = await compact_messages(msgs, llm)
    assert err is None
    assert len(compacted) == _KEEP_RECENT + 1
    assert isinstance(compacted[0], SystemMessage)
    assert "上下文摘要" in compacted[0].content
    assert llm.invoke_count == 1


@pytest.mark.asyncio
async def test_compact_messages_failure_degrades():
    msgs = [HumanMessage(content=f"问题{i}") for i in range(10)]
    compacted, err = await compact_messages(msgs, _FailingLLM())
    assert err is not None
    assert "COMPACTION_FAILED" in err
    assert compacted is msgs


@pytest.mark.asyncio
async def test_compact_messages_skips_when_few():
    msgs = [HumanMessage(content="问题1"), AIMessage(content="回答1")]
    compacted, err = await compact_messages(msgs, _MockLLM())
    assert err is None
    assert compacted is msgs
