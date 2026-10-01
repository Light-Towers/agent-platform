# -*- coding: utf-8 -*-
"""密钥指纹（DUP-1 / CodeQL weak-sensitive-data-hashing 收口）单元测试。

覆盖内核 ``agent_core.guardrails.auth`` 的三个新契约：
- ``fingerprint``：HMAC-SHA256 + 服务端 pepper + 截断下限；
- ``derive_thread_id``：会话身份格式与强度（替代散点 ``sha256(...)[:12]``）；
- ``legacy_thread_id``：迁移映射可计算（旧格式不漂移）。
"""

import hashlib

import pytest

from agent_core.guardrails.auth import (
    ENV_SECURITY_PEPPER,
    MIN_FINGERPRINT_HEX,
    THREAD_ID_DIGEST_HEX,
    THREAD_ID_PREFIX,
    derive_thread_id,
    fingerprint,
    legacy_thread_id,
    resolve_client_key,
)

# ---------------------------------------------------------------------------
# fingerprint：稳定性 / 区分度 / pepper 作用
# ---------------------------------------------------------------------------


def test_fingerprint_stable_for_same_secret():
    assert fingerprint("secret-a") == fingerprint("secret-a")


def test_fingerprint_differs_for_different_secrets():
    assert fingerprint("secret-a") != fingerprint("secret-b")


def test_fingerprint_full_length_is_sha256_hex_width():
    assert len(fingerprint("secret-a")) == 64
    assert all(c in "0123456789abcdef" for c in fingerprint("secret-a"))


def test_fingerprint_honours_length_truncation_at_floor():
    digest = fingerprint("secret-a", length=MIN_FINGERPRINT_HEX)
    assert len(digest) == MIN_FINGERPRINT_HEX
    # 截断是取前缀（同一实现下可预测）
    assert fingerprint("secret-a").startswith(digest)


@pytest.mark.parametrize("bad_length", [12, 1, 31, 65, -1])
def test_fingerprint_rejects_weak_or_out_of_range_length(bad_length):
    """48bit 截断（历史 ``[:12]``）在本 API 上不可能再被写出来。"""
    with pytest.raises(ValueError):
        fingerprint("secret-a", length=bad_length)


def test_fingerprint_is_pepper_dependent(monkeypatch):
    """同密钥在不同 pepper（=不同部署）下摘要不同 → 跨部署不可关联。"""
    monkeypatch.delenv(ENV_SECURITY_PEPPER, raising=False)
    without_pepper = fingerprint("secret-a")
    monkeypatch.setenv(ENV_SECURITY_PEPPER, "pepper-x")
    with_pepper = fingerprint("secret-a")
    assert without_pepper != with_pepper


def test_fingerprint_is_not_plain_sha256(monkeypatch):
    """CodeQL 判定要点：不再是裸 sha256(secret)。"""
    monkeypatch.delenv(ENV_SECURITY_PEPPER, raising=False)
    assert fingerprint("secret-a") != hashlib.sha256(b"secret-a").hexdigest()


def test_fingerprint_uses_hmac_construction(monkeypatch):
    """与手工 HMAC-SHA256(pepper, secret) 等价（锁死算法，防无意改回裸哈希）。"""
    import hmac as _hmac

    monkeypatch.setenv(ENV_SECURITY_PEPPER, "pepper-y")
    expected = _hmac.new(b"pepper-y", b"secret-a", hashlib.sha256).hexdigest()
    assert fingerprint("secret-a") == expected


# ---------------------------------------------------------------------------
# derive_thread_id：会话身份
# ---------------------------------------------------------------------------


def test_derive_thread_id_format():
    tid = derive_thread_id("secret-a")
    assert tid.startswith(THREAD_ID_PREFIX)
    assert len(tid) == len(THREAD_ID_PREFIX) + THREAD_ID_DIGEST_HEX  # 128bit，非旧 48bit


def test_derive_thread_id_stable_and_isolating():
    assert derive_thread_id("key-a") == derive_thread_id("key-a")
    assert derive_thread_id("key-a") != derive_thread_id("key-b")


def test_derive_thread_id_differs_from_legacy_format():
    """升级后同一密钥必须落到新会话身份（否则迁移脚本无意义）。"""
    assert derive_thread_id("secret-a") != legacy_thread_id("secret-a")


def test_derive_thread_id_none_and_empty_are_equivalent():
    assert derive_thread_id(None) == derive_thread_id("")


def test_legacy_thread_id_keeps_old_derivation():
    """迁移映射的前提：旧格式仍可精确复算（勿改此实现）。"""
    assert legacy_thread_id("secret-a") == "user-" + hashlib.sha256(b"secret-a").hexdigest()[:12]


# ---------------------------------------------------------------------------
# resolve_client_key：限流桶 key 也走同一实现（消除第 3 处散点）
# ---------------------------------------------------------------------------


def test_resolve_client_key_uses_fingerprint(monkeypatch):
    monkeypatch.setenv(ENV_SECURITY_PEPPER, "pepper-z")
    key = resolve_client_key({"x-api-key": "secret"}, "1.2.3.4", auth_enabled=True)
    assert key == f"key:{fingerprint('secret')}"
    assert key != f"key:{hashlib.sha256(b'secret').hexdigest()}"


def test_resolve_client_key_still_falls_back_to_ip():
    assert resolve_client_key({}, "1.2.3.4", auth_enabled=False) == "ip:1.2.3.4"
