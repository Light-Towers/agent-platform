# -*- coding: utf-8 -*-
"""
LLM 客户端注册表（框架无关内核，源自 zhiku app/lm/lm_utils 的缓存 + 配置层）。

- ``register_provider``：注册一个 provider（实现 ``BaseLLMProvider`` 协议）。
- ``get_llm_client``：按 provider 名解析并**带缓存**构造客户端；缓存键含
  (provider, model, json_mode, api_key_slot, base_url, extra_body) 以保障不同
  配置互不串。

WS-8 缓存治理：
- 缓存为上限 ``_MAX_CACHE`` 的 LRU（长进程不无限增长）；
- B7b-1（方案 §4.3）：cache key 放**进程内不透明 slot id**（``_SLOTS``）而非密钥
  摘要——上游 provider 凭据自此不再流入任何摘要函数（切断 ``#38`` 的链③）。slot 按
  凭据值幂等分配，故「换密钥 ⇒ 新 slot ⇒ 不命中旧客户端」的区分度与原摘要方案等价保留。

框架无关：核心层不依赖 langchain / app.conf；默认模型不再硬编码 ``qwen3-32b``，
由 provider 的 ``default_model`` 或调用方传入决定。
"""

import threading
from collections import OrderedDict
from typing import Any, Dict, Optional

from agent_core.llm.providers import BaseLLMProvider, OpenAICompatibleProvider
from agent_core.logging import get_logger

logger = get_logger(__name__)

# 已注册的 provider（name -> provider 实例）
_PROVIDERS: Dict[str, BaseLLMProvider] = {}

# 全局客户端缓存（WS-8：上限 LRU，避免长进程无限增长）
_MAX_CACHE = 64
_CLIENT_CACHE: "OrderedDict[tuple, Any]" = OrderedDict()
_CACHE_LOCK = threading.Lock()

# 预注册内置 openai 兼容适配器
_DEFAULT_OPENAI_PROVIDER = OpenAICompatibleProvider()
_PROVIDERS[_DEFAULT_OPENAI_PROVIDER.name] = _DEFAULT_OPENAI_PROVIDER

# 凭据 slot 表（B7b-1）：slot_id -> provider 凭据，仅作「凭据 → 不透明 slot」的
# 幂等映射载体（查找靠逐值比较）；构造客户端仍直接用调用方传入的凭据，
# 不从本表读回（避开重置窗口的读回竞态）。
# 上限 ``_MAX_SLOTS`` 与客户端缓存同量级，超限整表重置，保证明文驻留有界。
# 这不是新增暴露面：客户端对象（如 ChatOpenAI）本就长期持有 api_key 明文，
# 且正存放在 ``_CLIENT_CACHE`` 里；本表只是把「密钥 → 缓存键」换成「slot → 缓存键」。
# 锁顺序固定为 ``_SLOT_LOCK`` -> ``_CACHE_LOCK``（仅超限重置一处嵌套）；
# ``_cache_get`` / ``_cache_put`` 只取 ``_CACHE_LOCK``，无反向嵌套，故无死锁。
_MAX_SLOTS = 64
_EMPTY_SLOT = 0
_SLOTS: Dict[int, str] = {}
_SLOT_SEQ = 0
_SLOT_LOCK = threading.Lock()


def _slot_for_api_key(api_key: Optional[str]) -> int:
    """凭据 → 进程内不透明 slot id（B7b-1）。

    - 同值幂等复用同一 slot，不同值必得不同 slot ⇒ 缓存键保留密钥区分度；
    - 空凭据归 ``_EMPTY_SLOT``，不占表位；
    - **绝不对凭据做摘要或哈希**：本函数存在的全部意义就是切断「凭据 → 摘要」通路，
      不得为省一次遍历而改回内核指纹实现（有守门用例禁止本模块出现摘要通路）。
    """
    global _SLOT_SEQ
    if not api_key:
        return _EMPTY_SLOT
    with _SLOT_LOCK:
        for slot, stored in _SLOTS.items():
            if stored == api_key:
                return slot
        if len(_SLOTS) >= _MAX_SLOTS:
            # 密钥漂移超上限：整表重置并同步清客户端缓存——否则 slot id 复用会让
            # 新密钥撞上旧密钥遗留的客户端实例（正确性优先于命中率）。
            _SLOTS.clear()
            _SLOT_SEQ = 0
            clear_cache()
            logger.info("LLM 凭据 slot 表达上限 %s，已重置 slot 与客户端缓存", _MAX_SLOTS)
        _SLOT_SEQ += 1
        _SLOTS[_SLOT_SEQ] = api_key
        return _SLOT_SEQ


def _cache_get(key: tuple) -> Any:
    with _CACHE_LOCK:
        if key in _CLIENT_CACHE:
            _CLIENT_CACHE.move_to_end(key)
            return _CLIENT_CACHE[key]
    return None


def _cache_put(key: tuple, client: Any) -> None:
    with _CACHE_LOCK:
        _CLIENT_CACHE[key] = client
        _CLIENT_CACHE.move_to_end(key)
        while len(_CLIENT_CACHE) > _MAX_CACHE:
            _CLIENT_CACHE.popitem(last=False)


def register_provider(provider: BaseLLMProvider) -> None:
    """注册一个 LLM provider（同名覆盖；覆盖即清空客户端缓存）。

    同名覆盖意味着旧 provider 实例已被弃用，其构造出的客户端必须失效（方案 §4.3：
    密钥不再进缓存键后，旧实例不能靠“键不同”自然逸出）。
    """
    replaced = provider.name in _PROVIDERS
    _PROVIDERS[provider.name] = provider
    if replaced:
        clear_cache()
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

    # B7b-1：凭据以不透明 slot id 入键（不进任何摘要）；LRU 命中时刷新新鲜度
    api_key_slot = _slot_for_api_key(api_key)
    cache_key = (
        provider, target_model, json_mode, api_key_slot,
        base_url, temperature, repr(extra_body), repr(sorted(kwargs.items())),
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        # 日志只打非凭据维度：slot id 虽不透明，但仍由凭据数据流而来，不得入日志 sink
        # （CodeQL `py/clear-text-logging-sensitive-data` 正是按这条数据流报的，有 AST 守门用例拦截回归）。
        logger.debug(
            "LLM 客户端缓存命中：provider=%s model=%s json_mode=%s",
            provider, target_model, json_mode,
        )
        return cached

    client = prov.build(
        model=target_model,
        json_mode=json_mode,
        api_key=api_key,
        base_url=base_url,
        temperature=temperature,
        extra_body=extra_body,
        **kwargs,
    )
    _cache_put(cache_key, client)
    return client


def clear_cache() -> None:
    """清空客户端缓存（测试 / 配置热更新用）。

    不动凭据 slot 表：slot 与缓存生命周期不同，保留它只为同一密钥仍映射同一 slot；
    单测需用例间完全隔离时，额外清空 ``_SLOTS``。
    """
    with _CACHE_LOCK:
        _CLIENT_CACHE.clear()


__all__ = ["register_provider", "get_llm_client", "clear_cache", "BaseLLMProvider", "OpenAICompatibleProvider"]
