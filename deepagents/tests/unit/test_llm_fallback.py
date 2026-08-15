"""Test model fallback routing in agent/llm.py."""
import pytest
import os


class TestFallbackModel:
    """Test _FallbackModel proxy behaviour (without real API calls)."""

    @pytest.fixture(autouse=True)
    def _setup_env(self, monkeypatch):
        """Ensure env vars are set so agent.llm can import."""
        monkeypatch.setenv("OPENAI_BASE_URL", "https://dashscope.example.com/v1")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("LLM_QWEN_MAX", "qwen-max")
        monkeypatch.delenv("LLM_QWEN_FALLBACK", raising=False)

    def test_fallback_proxy_getattr(self):
        from agent.llm import _FallbackModel

        class FakeModel:
            def invoke(self, x):
                return f"invoked:{x}"

            def stream(self, x):
                yield f"stream:{x}"

            def bind_tools(self, tools):
                return f"bound:{len(tools)}"

        primary = FakeModel()
        fallback = FakeModel()
        proxy = _FallbackModel(primary, fallback)

        assert proxy.invoke("hello") == "invoked:hello"
        assert list(proxy.stream("hi")) == ["stream:hi"]
        assert proxy.bind_tools(["t1", "t2"]) == "bound:2"

    def test_fallback_switches_on_error(self):
        from agent.llm import _FallbackModel

        class FailingModel:
            def invoke(self, x):
                raise RuntimeError("primary down")

        class GoodModel:
            def invoke(self, x):
                return "fallback:ok"

        primary = FailingModel()
        fallback = GoodModel()
        proxy = _FallbackModel(primary, fallback)

        # First call fails on primary, succeeds on fallback
        result = proxy.invoke("test")
        assert result == "fallback:ok"

        # Subsequent calls go directly to fallback (cached)
        result2 = proxy.invoke("test2")
        assert result2 == "fallback:ok"

    def test_fallback_no_fallback_raises(self):
        from agent.llm import _FallbackModel

        class FailingModel:
            def invoke(self, x):
                raise RuntimeError("primary down")

        primary = FailingModel()
        proxy = _FallbackModel(primary, None)

        with pytest.raises(RuntimeError, match="primary down"):
            proxy.invoke("test")

    def test_fallback_repr(self):
        from agent.llm import _FallbackModel

        class M:
            def __repr__(self):
                return "FakeModel()"

        proxy = _FallbackModel(M(), None)
        assert "FakeModel" in repr(proxy)


class TestCreateFallbackModel:
    """Test create_fallback_model() with controlled env vars.

    Tests call create_fallback_model() directly after monkeypatching os.environ,
    so they are NOT affected by the real .env file (load_dotenv already ran at
    module import time; monkeypatch overrides os.environ lookups for subsequent
    os.getenv() calls within the test).
    """

    def test_no_fallback_returns_primary(self, monkeypatch):
        monkeypatch.setenv("OPENAI_BASE_URL", "https://dashscope.example.com/v1")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("LLM_QWEN_MAX", "qwen-max")
        monkeypatch.delenv("LLM_QWEN_FALLBACK", raising=False)

        from agent.llm import create_fallback_model, _FallbackModel
        m = create_fallback_model()
        assert not isinstance(m, _FallbackModel)

    def test_missing_primary_config_raises(self, monkeypatch):
        """Without API_KEY/BASE_URL, create_fallback_model() should raise."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        monkeypatch.delenv("LLM_QWEN_MAX", raising=False)

        from agent.llm import create_fallback_model
        with pytest.raises(RuntimeError, match="主模型配置缺失"):
            create_fallback_model()
