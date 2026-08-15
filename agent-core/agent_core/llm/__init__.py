# -*- coding: utf-8 -*-
"""
LLM 客户端子包（框架无关内核）。

- ``providers``：``BaseLLMProvider`` 协议 + ``OpenAICompatibleProvider``（langchain-openai 可选 extra）；
- ``registry``：``register_provider`` / ``get_llm_client``（带缓存，去硬编码）。

核心协议层零第三方依赖；仅使用 openai 适配器时才需 ``llm-openai`` extra。
"""

from agent_core.llm.providers import BaseLLMProvider, OpenAICompatibleProvider
from agent_core.llm.registry import clear_cache, get_llm_client, register_provider

__all__ = [
    "BaseLLMProvider",
    "OpenAICompatibleProvider",
    "register_provider",
    "get_llm_client",
    "clear_cache",
]
