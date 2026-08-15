# -*- coding: utf-8 -*-
"""
LLM 客户端注册表（框架无关内核，源自 zhiku app/lm/lm_utils 的缓存 + 配置层）。

- ``register_provider``：注册一个 provider（实现 ``BaseLLMProvider`` 协议）。
- ``get_llm_client``：按 provider 名解析并**带缓存**构造客户端；缓存键含
  (provider, model, json_mode, api_key, base_url, extra_body) 以保障不同配置互不串。

框架无关：核心层不依赖 langchain / app.conf；默认模型不再硬编码 ``qwen3-32b``，
由 provider 的 ``default_model`` 或调用方传入决定。
"""

from typing import Any, Dict, Optional

from agent_core.llm.providers import BaseLLMProvider, OpenAICompatibleProvider
from agent_core.logging import get_logger

logger = get_logger(__name__)

# 已注册的 provider（name -> provider 实例）
_PROVIDERS: Dict[str, BaseLLMProvider] = {}
# 全局客户端缓存：键为配置元组，值为客户端实例
_CLIENT_CACHE: Dict[tuple, Any] = {}

# 预注册内置 openai 兼容适配器
_DEFAULT_OPENAI_PROVIDER = OpenAICompatibleProvider()
_PROVIDERS[_DEFAULT_OPENAI_PROVIDER.name] = _DEFAULT_OPENAI_PROVIDER


def register_provider(provider: BaseLLMProvider) -> None:
    """注册一个 LLM provider（同名覆盖）。"""
    _PROVIDERS[provider.name] = provider
    logger.info("已注册 LLM provider: %s", provider.name)


def get_llm_client(
    model: Optional[str] = None,
    json_mode: bool = False,
    *,
    provider: str = "openai",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    temperature: float = 0.1,
    extra_body: Optional[dict] = None,
    **kwargs: Any,
) -> Any:
    """
    获取带缓存的 LLM 客户端实例。

    :param model: 模型名；None 时使用 provider.default_model。
    :param json_mode: 是否开启 JSON 结构化输出。
    :param provider: provider 名（默认 ``openai`` 内置兼容适配器）。
    :param api_key: API 密钥（必填，由宿主注入）。
    :param base_url: API 基础地址（必填，由宿主注入）。
    :param temperature: 采样温度。
    :param extra_body: 厂商私有参数透传（如 ``{"enable_thinking": False}``，由调用方决定）。
    :param kwargs: 透传给 provider.build 的其余参数。
    :return: 客户端实例（优先取缓存）。
    :raise KeyError: provider 未注册。
    :raise ValueError: 模型名与 provider 默认均为空；或缺少 api_key/base_url。
    """
    prov = _PROVIDERS.get(provider)
    if prov is None:
        raise KeyError(f"未注册的 LLM provider: {provider}（可用：{list(_PROVIDERS)}）")

    target_model = model or prov.default_model
    if not target_model:
        raise ValueError("模型名未指定：请传 model 或设置 provider.default_model")

    cache_key = (provider, target_model, json_mode, api_key, base_url, temperature, repr(extra_body), repr(sorted(kwargs.items())))
    if cache_key in _CLIENT_CACHE:
        logger.debug("LLM 客户端缓存命中：provider=%s model=%s json_mode=%s", provider, target_model, json_mode)
        return _CLIENT_CACHE[cache_key]

    client = prov.build(
        model=target_model,
        json_mode=json_mode,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        extra_body=extra_body,
        **kwargs,
    )
    _CLIENT_CACHE[cache_key] = client
    return client


def clear_cache() -> None:
    """清空客户端缓存（测试 / 配置热更新用）。"""
    _CLIENT_CACHE.clear()


__all__ = ["register_provider", "get_llm_client", "clear_cache", "BaseLLMProvider", "OpenAICompatibleProvider"]
