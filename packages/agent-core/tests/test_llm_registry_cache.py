# -*- coding: utf-8 -*-
"""WS-8：LLM 客户端缓存治理单测（LRU 淘汰 + 凭据 slot 化 + ChatModel 协议）。"""

from __future__ import annotations

import ast
import hashlib
import pathlib

from agent_core.llm import registry
from agent_core.llm.protocols import ChatModel
from agent_core.llm.providers import BaseLLMProvider


class _FakeProvider(BaseLLMProvider):
    """构造计数型 fake provider：验证缓存命中/淘汰时客户端实例的构造次数。

    ``seen_keys`` 用于验证 ``prov.build`` 仍拿到明文凭据（客户端必须真能鉴权，
    slot 化只改缓存键形态，不得把凭据弄丢）。
    """

    name = "fake"
    default_model = "fake-model"

    def __init__(self):
        self.builds = 0
        self.seen_keys: list = []

    def build(self, **kwargs):
        self.builds += 1
        self.seen_keys.append(kwargs.get("api_key"))
        return object()


def _setup(monkeypatch=None):
    registry.clear_cache()
    registry._SLOTS.clear()
    registry._SLOT_SEQ = 0
    prov = _FakeProvider()
    registry.register_provider(prov)
    return prov


def test_cache_hit_same_instance():
    prov = _setup()
    c1 = registry.get_llm_client(model="m", api_key="k", base_url="http://x", provider="fake")
    c2 = registry.get_llm_client(model="m", api_key="k", base_url="http://x", provider="fake")
    assert c1 is c2
    assert prov.builds == 1


def test_cache_key_carries_slot_not_any_digest():
    """B7b-1（取代原「键内必含指纹」断言）：键放不透明 slot，明文与任何摘要都不进键。

    新契约只关心语义：键内不得出现凭据明文，也不得出现凭据的**任何**摘要形态
    （旧契约曾经内核指纹写进键位，那个入口函数已随 B7b 全批删除 ⇒ 本用例改为
    穷举常见摘要算法 + 常见截断长度做否定式断言，不收窄而是加严）。
    密钥区分度改由 slot 承担。
    """
    prov = _setup()
    registry.get_llm_client(model="m", api_key="sk-secret-123", base_url="http://x", provider="fake")
    keys = list(registry._CLIENT_CACHE.keys())
    assert len(keys) == 1
    slot = keys[0][3]
    # 原摘要位现为整数 slot，凭据本体只存在 slot 表里
    assert isinstance(slot, int)
    assert slot != registry._EMPTY_SLOT
    assert registry._SLOTS[slot] == "sk-secret-123"
    # 构造仍拿到明文凭据（slot 化不得弄丢客户端鉴权所需信息）
    assert prov.seen_keys == ["sk-secret-123"]
    # 键成分里既无明文，也无任何摘要（含旧 48bit 截断与 128bit 两种长度）
    assert "sk-secret-123" not in repr(keys[0])
    cred = b"sk-secret-123"
    digests: set[str] = set()
    for algo in ("md5", "sha1", "sha224", "sha256", "sha384", "sha512"):
        full = hashlib.new(algo, cred).hexdigest()
        digests |= {full, full[:12], full[:32]}
    assert not set(keys[0]) & digests, keys[0]


def test_changed_api_key_does_not_hit_old_client():
    """方案 §7 验收 4（§4.3 取舍的守门用例）：密钥变更 → slot 更替 → 不命中旧客户端。"""
    prov = _setup()
    c1 = registry.get_llm_client(model="m", api_key="sk-old", base_url="http://x", provider="fake")
    c2 = registry.get_llm_client(model="m", api_key="sk-new", base_url="http://x", provider="fake")
    assert c1 is not c2
    assert prov.builds == 2
    assert prov.seen_keys == ["sk-old", "sk-new"]
    # 同值幂等：回到旧密钥仍复用旧实例，不因遍历顺序变化而重建
    assert registry.get_llm_client(model="m", api_key="sk-old", base_url="http://x", provider="fake") is c1
    assert prov.builds == 2
    assert len(registry._SLOTS) == 2


def test_empty_api_key_uses_dedicated_slot_and_leaves_table_clean():
    """无凭据归专用 slot，不占表位（避免 None 驻留与额外分配）。"""
    _setup()
    registry.get_llm_client(model="m", api_key=None, base_url="http://x", provider="fake")
    key = next(iter(registry._CLIENT_CACHE))
    assert key[3] == registry._EMPTY_SLOT
    assert not registry._SLOTS


def test_slot_table_resets_at_cap_and_clears_clients(monkeypatch):
    """明文驻留有界：达上限整表重置，并同步清客户端缓存（防 slot id 复用串到旧实例）。"""
    prov = _setup()
    monkeypatch.setattr(registry, "_MAX_SLOTS", 2)
    registry.get_llm_client(model="m", api_key="k1", base_url="http://x", provider="fake")
    registry.get_llm_client(model="m", api_key="k2", base_url="http://x", provider="fake")
    assert len(registry._CLIENT_CACHE) == 2
    registry.get_llm_client(model="m", api_key="k3", base_url="http://x", provider="fake")
    # 重置后表内只剩新密钥；旧客户端全失效，不会让 k3 复用 k1 的实例
    assert list(registry._SLOTS.values()) == ["k3"]
    assert len(registry._CLIENT_CACHE) == 1
    assert prov.builds == 3


def test_register_provider_overwrite_clears_client_cache():
    """同名覆盖 provider 时旧客户端必须失效（方案 §4.3）。"""
    prov1 = _setup()
    registry.get_llm_client(model="m", api_key="k", base_url="http://x", provider="fake")
    assert len(registry._CLIENT_CACHE) == 1
    prov2 = _FakeProvider()
    registry.register_provider(prov2)
    assert not registry._CLIENT_CACHE
    registry.get_llm_client(model="m", api_key="k", base_url="http://x", provider="fake")
    assert prov2.builds == 1
    assert prov1.builds == 1  # 旧 provider 不再被调用


def test_registry_source_has_no_credential_digest_path():
    """B7b-1 语义不变量：registry 模块内不得再出现摘要通路（防有人把密钥摘要拄回来）。

    全文扫描（含注释）而非仅 import：注释里的反例样本同样会被复制成真代码。
    B7b-5 会在此基础上再补正式 lint 门禁（方案 §5）。
    """
    src = pathlib.Path(registry.__file__).read_text(encoding="utf-8")
    for forbidden in ("hashlib", "hmac", "fingerprint", "sha256", "digest", "api_key_hash"):
        assert forbidden not in src, f"registry 不应再出现摘要通路：{forbidden}"


# 凭据及其派生值：不得作为日志调用的实参（B7b-1 实施时曾把 ``api_key_slot`` 写进
# ``logger.debug``，被 CodeQL ``py/clear-text-logging-sensitive-data`` 报为本 PR 新增 high 告警）。
_CREDENTIAL_NAMES = {"api_key", "api_key_slot", "secret", "token"}


def test_no_credential_value_reaches_logger_calls():
    """AST 守门：registry 内任何 ``logger.*`` 的实参不得引用凭据或其派生值。

    用 AST 而非文本 grep：本不变量的真实形态是「值进了 sink」，文本匹配既会被换行/重排
    绕过、又会把「注释里提到该名字」误判为违规。
    """
    src = pathlib.Path(registry.__file__).read_text(encoding="utf-8")
    offenders = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        recv = node.func.value
        if not (isinstance(recv, ast.Name) and recv.id == "logger"):
            continue
        for arg in [*node.args, *(kw.value for kw in node.keywords)]:
            for sub in ast.walk(arg):
                if isinstance(sub, ast.Name) and sub.id in _CREDENTIAL_NAMES:
                    offenders.append((node.lineno, sub.id))
    assert not offenders, f"凭据/凭据派生值进入日志实参：{offenders}"


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
