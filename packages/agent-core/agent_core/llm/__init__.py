# -*- coding: utf-8 -*-
"""
LLM 客户端子包（框架无关内核）。

- ``providers``：``BaseLLMProvider`` 协议 + ``OpenAICompatibleProvider``（langchain-openai 可选 extra）；
- ``registry``：``register_provider`` / ``get_llm_client``（带缓存，去硬编码；WS-8：LRU + 密钥摘要）；
- ``protocols``：``ChatModel`` 最小类型契约（WS-8，供降级/重试组合层标注）。

核心协议层零第三方依赖；仅使用 openai 适配器时才需 ``llm-openai`` extra。
"""

from agent_core.llm.protocols import ChatModel
from agent_core.llm.providers import BaseLLMProvider, OpenAICompatibleProvider
from agent_core.llm.registry import clear_cache, get_llm_client, register_provider

__all__ = [
    "BaseLLMProvider",
    "OpenAICompatibleProvider",
    "ChatModel",
    "register_provider",
    "get_llm_client",
    "clear_cache",
    "LangChainFallbackModel",
]


def __getattr__(name: str):
    # LangChain 兼容子类依赖可选 extra；延迟导入避免内核强依赖。
    if name == "LangChainFallbackModel":
        from agent_core.llm.fallback_lc import LangChainFallbackModel

        return LangChainFallbackModel
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
