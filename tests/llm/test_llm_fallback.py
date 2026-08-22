"""验证降级标志可复位：主模型恢复后应切回主模型（修复永久降级缺陷模式）。"""

import asyncio

import pytest


class FakeMessage:
    def __init__(self, content: str):
        self.content = content


class FakePrimary:
    def __init__(self, fail_times: int):
        self.fail_times = fail_times
        self.calls = 0

    async def ainvoke(self, *args, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("primary down")
        return FakeMessage("primary-answer")

    def with_structured_output(self, schema):
        return self


class FakeFallback:
    def __init__(self):
        self.calls = 0

    async def ainvoke(self, *args, **kwargs):
        self.calls += 1
        return FakeMessage("fallback-answer")


async def test_degradation_flag_resets_after_recovery():
    from agent_server.agent.llm import FallbackChatModel

    primary = FakePrimary(fail_times=2)
    fallback = FakeFallback()
    model = FallbackChatModel(primary, fallback, failure_threshold=2, cooldown=0.01)

    # 前两次主模型失败 -> 走 fallback
    assert (await model.ainvoke("q")).content == "fallback-answer"
    assert (await model.ainvoke("q")).content == "fallback-answer"
    assert model.degraded

    # 冷却窗口内直接走 fallback，不试探主模型
    assert (await model.ainvoke("q")).content == "fallback-answer"
    assert primary.calls == 2

    # 冷却结束后试探主模型，成功则复位
    await asyncio.sleep(0.02)
    assert (await model.ainvoke("q")).content == "primary-answer"
    assert not model.degraded
    assert fallback.calls == 3


# ---------- WS-3：流式降级契约 ----------


class StreamPrimary:
    """主模型流式：fail_after 个 chunk 后抛异常（0 = 未产出即失败）。"""

    def __init__(self, fail_after: int):
        self.fail_after = fail_after

    def stream(self, *a, **k):
        for i in range(self.fail_after):
            yield f"p{i}"
        raise RuntimeError("stream broken")

    async def astream(self, *a, **k):
        for i in range(self.fail_after):
            yield f"p{i}"
        raise RuntimeError("stream broken")


class StreamFallback:
    def stream(self, *a, **k):
        yield "f0"
        yield "f1"

    async def astream(self, *a, **k):
        yield "f0"
        yield "f1"


def test_stream_switches_only_before_first_chunk():
    from agent_core.llm.fallback import FallbackChatModel

    # 未产出任何 chunk 即失败 → 允许切备模型重放
    model = FallbackChatModel(StreamPrimary(0), StreamFallback(), failure_threshold=5)
    assert list(model.stream("q")) == ["f0", "f1"]


def test_stream_midway_failure_raises_not_mix():
    from agent_core.llm.fallback import FallbackChatModel

    # 已产出 chunk 后失败 → 向上抛（不混杂备模型输出）
    model = FallbackChatModel(StreamPrimary(2), StreamFallback(), failure_threshold=5)
    gen = model.stream("q")
    assert next(gen) == "p0"
    assert next(gen) == "p1"
    with pytest.raises(RuntimeError):
        next(gen)


async def test_astream_midway_failure_raises_not_mix():
    from agent_core.llm.fallback import FallbackChatModel

    model = FallbackChatModel(StreamPrimary(1), StreamFallback(), failure_threshold=5)
    chunks = []
    with pytest.raises(RuntimeError):
        async for c in model.astream("q"):
            chunks.append(c)
    assert chunks == ["p0"]  # 无备模型混杂内容


async def test_astream_switches_before_first_chunk():
    from agent_core.llm.fallback import FallbackChatModel

    model = FallbackChatModel(StreamPrimary(0), StreamFallback(), failure_threshold=5)
    chunks = [c async for c in model.astream("q")]
    assert chunks == ["f0", "f1"]
