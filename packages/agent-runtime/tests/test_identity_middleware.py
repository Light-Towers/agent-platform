"""IdentityMiddleware 接线测试（ADR-0007 A3/A4）：纯 ASGI 驱动，真实 RS256 令牌 + HMAC 头。

验证中间件"绑定 tenant 到 ContextVar → 下游 server_tenant_id() 读到断言值 → 复位"，
以及四类信任决策：合法/非法 Bearer、合法/伪造内部头、observe 放行、enforce 缺失拒绝。
"""

from __future__ import annotations

import asyncio

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from agent_runtime.identity import (
    TokenClaims,
    mint_token,
    sign_internal_header,
    verify_internal_header,
    verify_token,
)
from agent_runtime.identity_middleware import IdentityMiddleware
from agent_runtime.workspace_registry import server_tenant_id

_prk = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIV = _prk.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()
PUB = _prk.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
).decode()
KEYS = {"k1": PUB}
ISS, AUD = "iss", "aud"
HMAC_KEY = b"internal-hmac-key-shared-secret"


def _verify(tok: str) -> TokenClaims:
    return verify_token(tok, public_keys=KEYS, issuer=ISS, audience=AUD, max_ttl=3600, leeway=0)


def _vheader(value: str):
    return verify_internal_header(value, key=HMAC_KEY, max_age=300)


def _run(mw_kwargs, headers, path="/x"):
    """驱动中间件包一个 echo-tenant 的下游 app，返回 (下游看到的 tenant, HTTP 状态)。"""
    seen: dict = {}

    async def downstream(scope, receive, send):
        seen["tenant"] = server_tenant_id(default="<unbound>")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    mw = IdentityMiddleware(downstream, **mw_kwargs)
    scope = {
        "type": "http", "method": "GET", "path": path, "query_string": b"", "scheme": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    sent: list = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        sent.append(msg)

    asyncio.run(mw(scope, receive, send))
    status = next((m["status"] for m in sent if m["type"] == "http.response.start"), None)
    return seen.get("tenant"), status


def _bearer(tenant="tenantA", user="userB"):
    tok = mint_token(tenant, user_id=user, private_key_pem=PRIV, kid="k1", issuer=ISS, audience=AUD)
    return {"Authorization": f"Bearer {tok}"}


def test_valid_bearer_binds_tenant():
    tenant, status = _run({"verify": _verify, "verify_header": None}, _bearer())
    assert status == 200 and tenant == "tenantA"


def test_forged_bearer_rejected():
    hdrs = _bearer()
    hdrs["Authorization"] = hdrs["Authorization"][:-3] + "AAA"  # 破坏签名
    tenant, status = _run({"verify": _verify, "verify_header": None}, hdrs)
    assert status == 401


def test_valid_internal_header_binds():
    val = sign_internal_header("tenantB", "userC", key=HMAC_KEY)
    tenant, status = _run(
        {"verify": _verify, "verify_header": _vheader},
        {"X-Internal-Tenant": val},
    )
    assert status == 200 and tenant == "tenantB"


def test_forged_internal_header_rejected():
    val = sign_internal_header("tenantB", None, key=HMAC_KEY)
    forged = val[:-2] + "ff"
    tenant, status = _run(
        {"verify": _verify, "verify_header": _vheader},
        {"X-Internal-Tenant": forged},
    )
    assert status == 401


def test_observe_no_credential_falls_through():
    # 无任何凭据、observe 模式、无单租户声明 → 放行，下游读不到绑定（default 生效）
    tenant, status = _run(
        {"verify": _verify, "verify_header": None, "enforce_missing": False, "single_tenant": None},
        {},
    )
    assert status == 200 and tenant == "<unbound>"


def test_single_tenant_binds_when_no_credential():
    tenant, status = _run(
        {"verify": _verify, "verify_header": None, "single_tenant": "solo"},
        {},
    )
    assert status == 200 and tenant == "solo"


def test_enforce_missing_rejects_anonymous():
    tenant, status = _run(
        {"verify": _verify, "verify_header": None, "enforce_missing": True, "single_tenant": None},
        {},
    )
    assert status == 401


def test_context_reset_after_request():
    # 请求结束后 ContextVar 复位：下一个无凭据 observe 请求不应看到上一请求的租户
    _run({"verify": _verify, "verify_header": None}, _bearer("tenantX"))
    tenant, status = _run(
        {"verify": _verify, "verify_header": None, "enforce_missing": False, "single_tenant": None},
        {},
    )
    assert tenant == "<unbound>"


def test_opaque_bearer_falls_through():
    # 非 JWT 的不透明 Bearer（如静态 API_KEY 放 Authorization）不当作租户凭据，observe 下交下游
    tenant, status = _run(
        {"verify": _verify, "verify_header": None, "enforce_missing": False, "single_tenant": None},
        {"Authorization": "Bearer some-static-api-key-not-a-jwt"},
    )
    assert status == 200 and tenant == "<unbound>"


def test_skip_path_passthrough():
    # /health 免鉴权：即便 enforce_missing 也放行
    tenant, status = _run(
        {"verify": _verify, "verify_header": None, "enforce_missing": True},
        {},
        path="/health",
    )
    assert status == 200  # 下游执行（health 200）


def test_unknown_kid_rejected():
    tok = mint_token("tenantA", private_key_pem=PRIV, kid="retired", issuer=ISS, audience=AUD)
    with pytest.raises(Exception):
        _verify(tok)  # kid 不在架公钥集 → IdentityError
