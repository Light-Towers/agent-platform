# -*- coding: utf-8 -*-
"""密钥指纹（DUP-1 / CodeQL weak-sensitive-data-hashing 收口）单元测试。

覆盖内核 ``agent_core.guardrails.auth`` 的三个新契约：
- ``fingerprint``：HMAC-SHA256 + 服务端 pepper + 截断下限；
- ``derive_thread_id``：会话身份格式与强度（替代散点 ``sha256(...)[:12]``）；
- ``legacy_thread_id``：迁移映射可计算（旧格式不漂移）。

另含 B7b-2 对链②的**反向**守门：``resolve_client_key`` 与凭据摘要彻底无关
（旧契约「限流桶 key 也走同一 fingerprint 实现」已于 B7b-2 作废，见文件末段）。
"""

import ast
import hashlib
import inspect
import pathlib

import pytest

from agent_core.guardrails import auth as auth_module

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
# resolve_client_key：B7b-2 已拆链②（旧契约「桶键走 fingerprint 摘要」作废）
# 下列守门锁的是「凭据进不了限流桶」这一语义，而非某个参数名。
# ---------------------------------------------------------------------------


def test_resolve_client_key_signature_cannot_receive_credential():
    """签名级守门：只接受 IP 与已断言主体（旧签名的 ``headers``/``auth_enabled`` 正是链②入口）。"""
    params = set(inspect.signature(resolve_client_key).parameters)
    assert params == {"client_host", "subject"}


@pytest.mark.parametrize("credential", ["secret", "sk-123", "Bearer xyz", "a" * 64])
def test_resolve_client_key_bucket_independent_of_credential(credential, monkeypatch):
    """同一 IP 的桶键必与「带不带凭据 / 带哪把凭据 / pepper 为何」无关，且不含任何摘要形态。"""
    monkeypatch.setenv(ENV_SECURITY_PEPPER, "pepper-z")
    key = resolve_client_key("1.2.3.4")
    assert key == "ip:1.2.3.4"
    assert not key.startswith("key:")
    assert fingerprint(credential) not in key
    assert hashlib.sha256(credential.encode("utf-8")).hexdigest() not in key


def test_resolve_client_key_uses_subject_verbatim_not_digest(monkeypatch):
    """主体直用明文：不得为了「看起来更安全」而把主体过一道 ``fingerprint``（那只是新散点）。"""
    monkeypatch.setenv(ENV_SECURITY_PEPPER, "pepper-z")
    assert resolve_client_key("1.2.3.4", "tenant-α") == "sub:tenant-α"
    assert resolve_client_key("1.2.3.4", "  tenant-α  ") == "sub:tenant-α"


def test_only_session_identity_still_digests_credentials():
    """语义门禁（AST）：本模块内调 ``fingerprint`` 的函数只剩 ``derive_thread_id``。

    链②（``resolve_client_key``）已按 B7b-2 拆除 ⇒ 今后任何新增的「凭据 → 摘要」消费点
    都会在此红（对齐方案 §5：门禁守语义而非名字，改名绕过也会被拿到）。
    B7b-4 拆完链①后本断言应改为 ``== set()``（而非删掉这个用例）。
    """
    tree = ast.parse(pathlib.Path(inspect.getfile(auth_module)).read_text(encoding="utf-8"))
    callers = {
        func.name
        for func in ast.walk(tree)
        if isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef)
        for call in ast.walk(func)
        if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "fingerprint"
    }
    assert callers == {"derive_thread_id"}
