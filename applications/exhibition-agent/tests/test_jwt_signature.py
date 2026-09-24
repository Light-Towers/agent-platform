"""JWT HS256 验签测试（审核 W1）。

背景：全仓此前所有路径均 verify_signature=False，HS256 分支（encode_jwt 带密钥签名 /
decode_jwt 验签）生产首次执行才跑。本文件覆盖签名/验签闭环 + STRICT 档中间件拒绝路径。
"""

from __future__ import annotations

import base64
import json

import pytest

from exhibition_agent.middleware.context_codec import decode_jwt, encode_jwt
from exhibition_agent.middleware.execution_context_middleware import (
    AuthContextInvalidError,
    resolve_execution_context,
)
from exhibition_agent.testing_helpers import make_context_payload

_SECRET = "test-secret-key"


def _payload_b64(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def test_hs256_sign_and_verify_roundtrip():
    """encode_jwt(secret) 签名 → decode_jwt(verify_signature=True, secret) 验签通过。"""
    payload = make_context_payload()
    token = encode_jwt(payload, secret=_SECRET)
    assert token.split(".")[2], "签名段不应为空"
    decoded = decode_jwt(token, verify_signature=True, secret=_SECRET)
    assert decoded["user_id"] == payload["user_id"]
    assert decoded["tenant_id"] == payload["tenant_id"]


def test_hs256_rejects_tampered_payload():
    """payload 被篡改（保留原签名段）→ HS256 验签失败 ValueError。"""
    payload = make_context_payload()
    token = encode_jwt(payload, secret=_SECRET)
    header_b64, _, sig_b64 = token.split(".")
    forged = {**payload, "scopes": ["venue:secret-venue"]}
    tampered_token = f"{header_b64}.{_payload_b64(forged)}.{sig_b64}"
    with pytest.raises(ValueError, match="签名无效"):
        decode_jwt(tampered_token, verify_signature=True, secret=_SECRET)


def test_hs256_rejects_wrong_secret():
    """密钥不匹配 → ValueError 签名无效。"""
    payload = make_context_payload()
    token = encode_jwt(payload, secret=_SECRET)
    with pytest.raises(ValueError, match="签名无效"):
        decode_jwt(token, verify_signature=True, secret="wrong-secret")


def test_verify_signature_true_without_secret_raises():
    """verify_signature=True 但 secret 缺失 → ValueError（防静默跳过验签）。"""
    token = encode_jwt(make_context_payload())
    with pytest.raises(ValueError, match="secret 未提供"):
        decode_jwt(token, verify_signature=True, secret=None)


def test_strict_mode_rejects_unsigned_jwt():
    """STRICT 档 + 无签名 JWT（encode_jwt 不带 secret）→ 401 AUTH_CONTEXT_INVALID。"""
    unsigned = encode_jwt(make_context_payload())
    with pytest.raises(AuthContextInvalidError, match="签名无效"):
        resolve_execution_context(
            unsigned,
            mode="jwt",
            path="/api/query",
            skill="venue.schedule.query",
            jwt_secret=_SECRET,
            verify_signature=True,
        )


def test_strict_mode_accepts_valid_signature():
    """STRICT 档 + 正确 HS256 签名 JWT → 解析通过（生产首次执行路径已验证）。"""
    payload = make_context_payload()
    signed = encode_jwt(payload, secret=_SECRET)
    context = resolve_execution_context(
        signed,
        mode="jwt",
        path="/api/query",
        skill="venue.schedule.query",
        jwt_secret=_SECRET,
        verify_signature=True,
    )
    assert context.user_id == payload["user_id"]
