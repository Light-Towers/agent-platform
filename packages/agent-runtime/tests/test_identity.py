"""identity 模块测试（ADR-0007 A3/A4）：RS256 签/验、内部 HMAC 头、上下文绑定、启动守卫。

真实生成 RSA 密钥对（cryptography，随 PyJWT[crypto] 安装），无网络/无 DB。
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from agent_runtime.identity import (
    IdentityError,
    apply_tenant_context,
    mint_token,
    require_identity_startup_guard,
    resolve_startup_tenant_mode,
    sign_internal_header,
    verify_internal_header,
    verify_token,
)
from agent_runtime.workspace_registry import reset_tenant_context, reset_user_context, server_tenant_id

ISS = "test-issuer"
AUD = "test-audience"


def _keypair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    from cryptography.hazmat.primitives import serialization

    priv = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return priv, pub


PRIV, PUB = _keypair()
KEYS = {"k1": PUB}


def test_mint_and_verify_roundtrip():
    tok = mint_token("tenantA", user_id="userB", private_key_pem=PRIV, kid="k1", issuer=ISS, audience=AUD, ttl=900)
    claims = verify_token(tok, public_keys=KEYS, issuer=ISS, audience=AUD, max_ttl=3600, leeway=0)
    assert claims.tenant_id == "tenantA"
    assert claims.user_id == "userB"


def test_verify_rejects_tampered_token():
    tok = mint_token("tenantA", private_key_pem=PRIV, kid="k1", issuer=ISS, audience=AUD)
    bad = tok[:-3] + ("aaa" if tok[-3:] != "aaa" else "bbb")
    with pytest.raises(IdentityError):
        verify_token(bad, public_keys=KEYS, issuer=ISS, audience=AUD, max_ttl=3600, leeway=0)


def test_verify_rejects_expired():
    tok = mint_token("tenantA", private_key_pem=PRIV, kid="k1", issuer=ISS, audience=AUD, ttl=-100)
    with pytest.raises(IdentityError, match="验签|校验"):
        verify_token(tok, public_keys=KEYS, issuer=ISS, audience=AUD, max_ttl=3600, leeway=0)


def test_verify_rejects_missing_tenant_claim():
    now = int(time.time())
    tok = jwt.encode(
        {"sub": "u", "iat": now, "exp": now + 300, "iss": ISS, "aud": AUD},
        PRIV, algorithm="RS256", headers={"kid": "k1"},
    )
    with pytest.raises(IdentityError, match="tenant_id"):
        verify_token(tok, public_keys=KEYS, issuer=ISS, audience=AUD, max_ttl=3600, leeway=0)


def test_verify_rejects_overlong_ttl():
    tok = mint_token("tenantA", private_key_pem=PRIV, kid="k1", issuer=ISS, audience=AUD, ttl=99999)
    with pytest.raises(IdentityError, match="TTL"):
        verify_token(tok, public_keys=KEYS, issuer=ISS, audience=AUD, max_ttl=3600, leeway=0)


def test_verify_rejects_wrong_issuer():
    tok = mint_token("tenantA", private_key_pem=PRIV, kid="k1", issuer=ISS, audience=AUD)
    with pytest.raises(IdentityError):
        verify_token(tok, public_keys=KEYS, issuer="someone-else", audience=AUD, max_ttl=3600, leeway=0)


def test_kid_rotation_selects_matching_public_key():
    priv2, pub2 = _keypair()
    tok = mint_token("tenantA", private_key_pem=PRIV, kid="old", issuer=ISS, audience=AUD)
    # 新旧公钥并存（轮转窗口）→ 按 kid 命中旧公钥
    claims = verify_token(
        tok, public_keys={"old": PUB, "new": pub2}, issuer=ISS, audience=AUD, max_ttl=3600, leeway=0
    )
    assert claims.tenant_id == "tenantA"
    # 旧公钥已下线（只剩 new）→ 验签失败
    with pytest.raises(IdentityError):
        verify_token(tok, public_keys={"new": pub2}, issuer=ISS, audience=AUD, max_ttl=3600, leeway=0)


def test_internal_header_sign_and_verify():
    key = b"secret-hmac-key-32-bytes-long!!"
    hdr = sign_internal_header("tenantA", "userB", key=key)
    assert verify_internal_header(hdr, key=key, max_age=300) == ("tenantA", "userB")


def test_internal_header_missing_returns_none():
    assert verify_internal_header(None, key=b"k", max_age=300) is None
    assert verify_internal_header("", key=b"k", max_age=300) is None


def test_internal_header_forged_rejected():
    key = b"legit-key"
    hdr = sign_internal_header("tenantA", None, key=key)
    # 攻击者篡改租户位、用错误密钥无法重签
    tenant, user = verify_internal_header(hdr, key=key, max_age=300)
    assert tenant == "tenantA"
    # 篡改 payload 末位 ⇒ 被签名的 body 变化 ⇒ 先走验签不符分支。替换字符按构造
    # 保证 != 原字符（旧写法固定用 "x"，若 payload 末尾恰为 "x" 则退化为原串，判据静默失效）。
    payload = hdr.split(".")[1]
    forged = "v1." + payload[:-1] + ("x" if not payload.endswith("x") else "y") + "." + hdr.split(".")[2]
    assert forged != hdr, "伪造串与合法串相同 ⇒ 本用例没在校验签名，判据失效"
    with pytest.raises(IdentityError):
        verify_internal_header(forged, key=key, max_age=300)


def test_internal_header_expired():
    key = b"k"
    hdr = sign_internal_header("tenantA", None, key=key)
    with pytest.raises(IdentityError, match="过期"):
        verify_internal_header(hdr, key=key, max_age=-1)


def test_apply_tenant_context_binds_server_tenant_id():
    tok, utok = apply_tenant_context("tenantZ", "userY")
    try:
        assert server_tenant_id() == "tenantZ"
    finally:
        reset_tenant_context(tok)
        reset_user_context(utok)


def test_startup_mode_single_tenant(monkeypatch):
    monkeypatch.delenv("TENANT_JWT_PUBLIC_KEYS_FILE", raising=False)
    monkeypatch.setenv("SINGLE_TENANT", "onlyme")
    mode, tenant = resolve_startup_tenant_mode()
    assert mode == "single" and tenant == "onlyme"
    # 声明了单租户 → 守卫放行（不抛）
    monkeypatch.setenv("DEPLOY_ENFORCE_IDENTITY", "true")
    assert require_identity_startup_guard("test") == "single"


def test_startup_mode_jwt_when_keys_present(monkeypatch, tmp_path):
    keyf = tmp_path / "pubkeys.json"
    keyf.write_text('{"k1": "-----BEGIN PUBLIC KEY-----\\nMIIB\\n-----END PUBLIC KEY-----"}')
    monkeypatch.setenv("TENANT_JWT_PUBLIC_KEYS_FILE", str(keyf))
    mode, _ = resolve_startup_tenant_mode()
    assert mode == "jwt"


def test_startup_guard_fail_fast_when_insecure_and_enforced(monkeypatch):
    monkeypatch.delenv("TENANT_JWT_PUBLIC_KEYS_FILE", raising=False)
    monkeypatch.delenv("SINGLE_TENANT", raising=False)
    monkeypatch.setenv("DEPLOY_ENFORCE_IDENTITY", "true")
    with pytest.raises(RuntimeError, match="启动被拒"):
        require_identity_startup_guard("agent_server")
    # 未开强制 → 仅告警不抛，返回 insecure（开发/测试默认）
    monkeypatch.setenv("DEPLOY_ENFORCE_IDENTITY", "false")
    assert require_identity_startup_guard("agent_server") == "insecure"
