# -*- coding: utf-8 -*-
"""WS-8：LLM 客户端缓存治理单测（LRU 淘汰 + api_key 哈希 + ChatModel 协议）。"""

from __future__ import annotations

import hashlib

from agent_core.llm import registry
from agent_core.llm.protocols import ChatModel
from agent_core.llm.providers import BaseLLMProvider


class _FakeProvider(BaseLLMProvider):
    """构造计数型 fake provider：验证缓存命中/淘汰时客户端实例的构造次数。"""

    name = "fake"
    default_model = "fake-model"

    def __init__(self):
        self.builds = 0

    def build(self, **kwargs):
        self.builds += 1
        return object()


def _setup(monkeypatch=None):
    registry.clear_cache()
    prov = _FakeProvider()
    registry.register_provider(prov)
    return prov


def test_cache_hit_same_instance():
    prov = _setup()
    c1 = registry.get_llm_client(model="m", api_key="k", base_url="http://x", provider="fake")
    c2 = registry.get_llm_client(model="m", api_key="k", base_url="http://x", provider="fake")
    assert c1 is c2
    assert prov.builds == 1


def test_api_key_not_stored_plaintext_in_cache_key():
    _setup()
    registry.get_llm_client(model="m", api_key="sk-secret-123", base_url="http://x", provider="fake")
    digest = hashlib.sha256(b"sk-secret-123").hexdigest()
    keys = list(registry._CLIENT_CACHE.keys())
    assert len(keys) == 1
    # cache key 含摘要、不含明文密钥
    assert digest in keys[0]
    assert "sk-secret-123" not in repr(keys[0])


def test_lru_evicts_beyond_max():
    prov = _setup()
    # 填满超过 _MAX_CACHE 的不同配置
    for i in range(registry._MAX_CACHE + 4):
        registry.get_llm_client(
            model=f"m{i}", api_key="k", base_url="http://x", provider="fake"
        )
    assert len(registry._CLIENT_CACHE) == registry._MAX_CACHE
    assert prov.builds == registry._MAX_CACHE + 4


def test_lru_recently_used_survives():
    prov = _setup()
    first_model = "keep-me"
    registry.get_llm_client(model=first_model, api_key="k", base_url="http://x", provider="fake")
    # 再填 MAX-1 个配置，缓存恰好满（keep-me 在最旧位，未被淘汰）
    for i in range(registry._MAX_CACHE - 1):
        registry.get_llm_client(model=f"fill{i}", api_key="k", base_url="http://x", provider="fake")
    assert len(registry._CLIENT_CACHE) == registry._MAX_CACHE
    # 再访问 keep-me 刷新新鲜度（命中缓存，不重新构造）
    registry.get_llm_client(model=first_model, api_key="k", base_url="http://x", provider="fake")
    # 插入新配置触发淘汰：被淘汰的应是 fill0（最旧），keep-me 存活
    registry.get_llm_client(model="newcomer", api_key="k", base_url="http://x", provider="fake")
    models_in_cache = {k[1] for k in registry._CLIENT_CACHE.keys()}
    assert first_model in models_in_cache
    assert "fill0" not in models_in_cache
    # 总构造数 = 1(keep-me) + MAX-1(fill) + 1(newcomer)，keep-me 第二次为缓存命中
    assert prov.builds == registry._MAX_CACHE + 1


def test_chat_model_protocol_structural():
    class _Model:
        def invoke(self, *a, **k):
            return None

        async def ainvoke(self, *a, **k):
            return None

        def stream(self, *a, **k):
            yield None

        def astream(self, *a, **k):
            return None

    assert isinstance(_Model(), ChatModel)
