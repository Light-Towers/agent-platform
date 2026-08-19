"""验证降级标志可复位：主模型恢复后应切回主模型（修复永久降级缺陷模式）。"""

import asyncio


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
