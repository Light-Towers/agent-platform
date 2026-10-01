"""build_chat_model 的 Langfuse callbacks 单点注入测试（2026-09-25 断线修复）。

背景：原实现在 lifespan 装配 ``app.state.callbacks`` 但全仓无消费方（断线），
LLM 观测从未生效。修复后收敛到 ``build_chat_model()`` 构造期单点注入——
LangChain runnable 构造期 callbacks 对该实例所有调用路径生效
（FallbackChatModel.invoke 直调 / bind_tools 返回的 primary runnable / BaseChatModel 机制）。

覆盖：
- 配置 langfuse 凭据 → callbacks 挂到 primary/fallback 构造参数；
- 未配置凭据 → callbacks 为空，行为与修复前一致（opt-in 降级）；
- LLM 未配置 → 返回 None（原有契约不变）。

langfuse SDK 是 federation 的 optional extra（根 venv 通常未安装），
故 handler 列表用 monkeypatch 注入桩对象，只测接线逻辑、不依赖 SDK。
"""

from __future__ import annotations

from typing import Any

from agent_server.agent.llm import build_chat_model
from agent_server.config import get_settings
from langchain_core.callbacks import BaseCallbackHandler


class _StubHandler(BaseCallbackHandler):
    """langfuse CallbackHandler 的测试替身（不依赖 langfuse SDK 是否安装）。"""


def _setenv_llm(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:9999/v1")
    monkeypatch.setenv("LLM_MODEL", "test-model")


def test_langfuse_callbacks_injected_at_construction(monkeypatch) -> None:
    _setenv_llm(monkeypatch)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_HOST", "http://localhost:3000")

    handlers: list[Any] = [_StubHandler()]
    monkeypatch.setattr(
        "agent_runtime.tracing.get_langfuse_callbacks", lambda **kwargs: handlers
    )

    get_settings.cache_clear()
    try:
        llm = build_chat_model()
    finally:
        get_settings.cache_clear()

    assert llm is not None
    assert llm.primary.callbacks == handlers, "primary 模型构造期 callbacks 未挂载"
    assert llm.fallback.callbacks == handlers, "fallback 模型构造期 callbacks 未挂载"


def test_no_langfuse_keys_leaves_callbacks_empty(monkeypatch) -> None:
    _setenv_llm(monkeypatch)
    for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"):
        monkeypatch.setenv(key, "")

    get_settings.cache_clear()
    try:
        llm = build_chat_model()
    finally:
        get_settings.cache_clear()

    assert llm is not None
    # opt-in 降级：无凭据时不得改变原有行为（不挂 callbacks）
    assert not getattr(llm.primary, "callbacks", None)
    assert not getattr(llm.fallback, "callbacks", None)


def test_llm_disabled_returns_none(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "")

    get_settings.cache_clear()
    try:
        assert build_chat_model() is None
    finally:
        get_settings.cache_clear()
