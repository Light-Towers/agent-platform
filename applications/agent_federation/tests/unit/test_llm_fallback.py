"""Test model fallback routing via agent/llm.py (LangChain adapter).

契约：``create_fallback_model`` 在有备用模型时返回 ``LangChainFallbackModel``
（BaseChatModel 子类）。降级语义完全由内核 ``FallbackChatModel`` 实现，本测试
用遵守 LangChain 消息协议的 FakeChatModel 验证「主失败→降级备→冷却到期→恢复」。
"""
import pytest

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage


class FakeChatModel(BaseChatModel):
    """可注入失败行为的 LangChain 假模型（遵守消息协议）。"""

    name: str = "fake"
    fail_times: int = 0  # 前 N 次调用抛错
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        from langchain_core.outputs import ChatGeneration, ChatResult

        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError(f"{self.name} down")
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=f"{self.name}:ok"))])


class TestFallbackModel:
    """LangChainFallbackModel 透传内核降级路由（无真实 API 调用）。"""

    @pytest.fixture(autouse=True)
    def _setup_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_BASE_URL", "https://dashscope.example.com/v1")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("LLM_QWEN_MAX", "qwen-max")
        monkeypatch.delenv("LLM_QWEN_FALLBACK", raising=False)

    def test_invoke_routes_to_primary(self):
        from agent.llm import LangChainFallbackModel

        primary = FakeChatModel(name="primary")
        fallback = FakeChatModel(name="fallback")
        proxy = LangChainFallbackModel(primary=primary, fallback=fallback)

        resp = proxy.invoke([HumanMessage(content="hi")])
        assert isinstance(resp, AIMessage)
        assert resp.content == "primary:ok"
        assert not proxy.degraded

    def test_switches_to_fallback_on_failure(self):
        from agent.llm import LangChainFallbackModel

        # failure_threshold=1：首次主失败即降级（连续失败计数达阈值）
        primary = FakeChatModel(name="primary", fail_times=5)
        fallback = FakeChatModel(name="fallback")
        proxy = LangChainFallbackModel(
            primary=primary, fallback=fallback, failure_threshold=1, cooldown=0.0
        )

        # 主失败 → 降级并走 fallback
        resp = proxy.invoke([HumanMessage(content="hi")])
        assert resp.content == "fallback:ok"
        assert proxy.degraded

    def test_recovers_after_cooldown(self):
        from agent.llm import LangChainFallbackModel

        primary = FakeChatModel(name="primary", fail_times=1)
        fallback = FakeChatModel(name="fallback")
        proxy = LangChainFallbackModel(
            primary=primary, fallback=fallback, failure_threshold=1, cooldown=0.0
        )

        # 首次失败 → 降级
        assert proxy.invoke([HumanMessage(content="x")]).content == "fallback:ok"
        assert proxy.degraded
        # 冷却窗口为 0，下一次回到主模型；主此时已成功 → 复位
        assert proxy.invoke([HumanMessage(content="y")]).content == "primary:ok"
        assert not proxy.degraded

    def test_stream_delegates(self):
        from agent.llm import LangChainFallbackModel
        from langchain_core.messages import AIMessageChunk
        from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

        class StreamModel(BaseChatModel):
            name: str = "s"

            @property
            def _llm_type(self) -> str:
                return "s"

            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content="s:ok"))])

            def _stream(self, messages, stop=None, run_manager=None, **kwargs):
                yield ChatGenerationChunk(message=AIMessageChunk(content=f"{self.name}:chunk"))

        primary = StreamModel()
        fallback = StreamModel()
        proxy = LangChainFallbackModel(primary=primary, fallback=fallback)
        chunks = list(proxy.stream([HumanMessage(content="hi")]))
        assert chunks[0].text == "s:chunk"

    def test_is_base_chat_model(self):
        from agent.llm import LangChainFallbackModel
        from langchain_core.language_models import BaseChatModel

        primary = FakeChatModel(name="primary")
        fallback = FakeChatModel(name="fallback")
        proxy = LangChainFallbackModel(primary=primary, fallback=fallback)
        assert isinstance(proxy, BaseChatModel)


class TestCreateFallbackModel:
    """create_fallback_model() 在有/无备用模型时的返回类型。"""

    def test_no_fallback_returns_single_model_adapter(self, monkeypatch):
        """无备用模型时仍返回 LangChainFallbackModel（单模型外壳）。

        P2.1：必须返回外壳而非裸 primary，否则 deepagents PyPI 包的 SummarizationMiddleware
        读不到 model.profile["max_input_tokens"]，会在小窗口模型（qwen-max 32K）下
        永不触发摘要。外壳的 fallback 为 None，profile 按主模型名解析窗口。
        """
        monkeypatch.setenv("OPENAI_BASE_URL", "https://dashscope.example.com/v1")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("LLM_QWEN_MAX", "qwen-max")
        monkeypatch.delenv("LLM_QWEN_FALLBACK", raising=False)

        from agent.llm import create_fallback_model, LangChainFallbackModel

        m = create_fallback_model()
        assert isinstance(m, LangChainFallbackModel)
        assert m._core.fallback is None
        # profile 暴露窗口，驱动 summarization 按窗口比例触发（而非硬编码 170K）
        assert m.profile["max_input_tokens"] == 30_000

    def test_with_fallback_returns_adapter(self, monkeypatch):
        monkeypatch.setenv("OPENAI_BASE_URL", "https://dashscope.example.com/v1")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("LLM_QWEN_MAX", "qwen-max")
        monkeypatch.setenv("LLM_QWEN_FALLBACK", "qwen-plus")

        from agent.llm import create_fallback_model, LangChainFallbackModel

        m = create_fallback_model()
        assert isinstance(m, LangChainFallbackModel)

    def test_missing_primary_config_raises(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        monkeypatch.delenv("LLM_QWEN_MAX", raising=False)

        from agent.llm import create_fallback_model

        with pytest.raises(RuntimeError, match="主模型配置缺失"):
            create_fallback_model()
