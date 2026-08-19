"""BaseSemanticCache 契约与 build_cache_key 单一真相测试（TB-4）。"""

import hashlib
import json

from agent_core.cache import BaseSemanticCache, build_cache_key


class TestBuildCacheKey:
    def test_deterministic(self):
        k1 = build_cache_key("refund", "如何退款", {"kefu": "v2"}, "t1", 0.0)
        k2 = build_cache_key("refund", "如何退款", {"kefu": "v2"}, "t1", 0.0)
        assert k1 == k2

    def test_distinct_intent(self):
        a = build_cache_key("refund", "如何退款", {}, "", 0.0)
        b = build_cache_key("order", "如何退款", {}, "", 0.0)
        assert a != b

    def test_distinct_kb_version_invalidates(self):
        old = build_cache_key("refund", "如何退款", {"kefu": "v1"}, "t1", 0.0)
        new = build_cache_key("refund", "如何退款", {"kefu": "v2"}, "t1", 0.0)
        assert old != new  # KB 版本变更自动失效旧缓存

    def test_distinct_tenant(self):
        a = build_cache_key("refund", "q", {}, "tenantA", 0.0)
        b = build_cache_key("refund", "q", {}, "tenantB", 0.0)
        assert a != b

    def test_gray_pct_affects_key(self):
        a = build_cache_key("refund", "q", {}, "t", 0.0)
        b = build_cache_key("refund", "q", {}, "t", 0.5)
        assert a != b

    def test_matches_legacy_deepagents_formula(self):
        """key 必须与 deepagents 旧本地实现逐字节一致，确保缓存不失效重算。"""
        intent, query, kb_versions, tenant, gray = "refund", "如何退款", {"kefu": "v2"}, "t1", 0.0
        kb_str = json.dumps(kb_versions, sort_keys=True)
        raw = f"{intent}|{query}|{kb_str}|{tenant}|{gray}"
        expected = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        assert build_cache_key(intent, query, kb_versions, tenant, gray) == expected

    def test_defaults_empty(self):
        k = build_cache_key("refund", "q")
        assert isinstance(k, str) and len(k) == 64


class TestBaseSemanticCacheProtocol:
    def test_runtime_checkable_on_conforming_class(self):
        class Impl:
            def get_stats(self):
                return {}

            def reset_stats(self) -> None:
                return None

        assert isinstance(Impl(), BaseSemanticCache)

    def test_runtime_checkable_rejects_non_conforming(self):
        class Bad:
            pass

        assert not isinstance(Bad(), BaseSemanticCache)
