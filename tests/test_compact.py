"""上下文压缩 compact 测试。"""

import pytest
from agent_core.tokenizer import count_messages, count_tokens, get_tokenizer
from agent_server.agent.compact import (
    _KEEP_RECENT,
    compact_messages,
    estimate_tokens,
    should_compact,
)
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage


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
    # 不写死具体值：OpenAI 系走 tiktoken 精确计数（启发式上界为 int((4+2)/1.5)=4），
    # 两种路径都应是合理的正数，且不超过启发式上界。
    assert tokens <= int((4 + 2) / 1.5) + 1


def test_estimate_tokens_accepts_model_arg():
    # model 透传不影响结果有效性（精确或启发式均可）
    msgs = [HumanMessage(content="x" * 200)]
    assert estimate_tokens(msgs) > 0
    assert estimate_tokens(msgs, "gpt-4o") > 0


def test_tokenizer_heuristic_fallback():
    # 非 OpenAI 模型 / tiktoken 不可用时走启发式：字符数 / 1.5
    assert count_tokens("") == 0
    # "你好世界" 为 4 个汉字 → 启发式 int(4/1.5)=2
    assert count_tokens("你好世界", model="qwen-max") == int(4 / 1.5)
    assert count_tokens("hello world", model=None) == int(11 / 1.5)


def test_tokenizer_openai_precise_when_available():
    # 若 tiktoken 可用，gpt-4o 应给出精确计数（与启发式不同）
    enc = get_tokenizer("gpt-4o")
    if enc is None:
        pytest.skip("tiktoken 未安装，跳过精确计数断言")
    precise = count_tokens("你好世界", model="gpt-4o")
    assert precise == len(enc.encode("你好世界"))
    assert precise != int(6 / 1.5)


def test_count_messages_mixed():
    msgs = [HumanMessage(content="abc"), {"content": "def"}, "raw"]
    # dict 与原始字符串都能被提取计数，总数应为三者之和
    assert count_messages(msgs) == count_tokens("abc") + count_tokens("def") + count_tokens("raw")


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
