"""联邦网关 X-Tenant-JWT 断言测试（ADR-0007 决策2=B1）。

纯 ASGI 驱动 IdentityMiddleware（token_header=X-Tenant-JWT + 联邦 api.context 桥接），
验证：合法 JWT 绑定到 get_tenant_context、伪造 401、缺头 observe 透传（不破坏现有 API_KEY 链路）。
"""

from __future__ import annotations

import asyncio

from agent_runtime.identity import mint_token, verify_token
from agent_runtime.identity_middleware import IdentityMiddleware
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from api.context import get_tenant_context
from api.identity_bridge import _apply, _reset

_prk = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIV = _prk.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()
PUB = _prk.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
).decode()
KEYS = {"k1": PUB}
ISS, AUD = "gw-iss", "gw-aud"


def _verify(tok):
    return verify_token(tok, public_keys=KEYS, issuer=ISS, audience=AUD, max_ttl=3600, leeway=0)


def _mw_kwargs():
    return {
        "token_header": "X-Tenant-JWT",
        "verify": _verify,
        "verify_header": None,
        "apply": _apply,
        "reset": _reset,
        "enforce_missing": False,
        "single_tenant": None,
    }


def _drive(headers):
    seen: dict = {}

    async def downstream(scope, receive, send):
        seen["tenant"] = get_tenant_context()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    mw = IdentityMiddleware(downstream, **_mw_kwargs())
    scope = {
        "type": "http", "method": "POST", "path": "/invoke", "scheme": "http", "query_string": b"",
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


def test_xtjwt_binds_federation_tenant_context():
    tok = mint_token("tenantA", user_id="u1", private_key_pem=PRIV, kid="k1", issuer=ISS, audience=AUD)
    tenant, status = _drive({"X-Tenant-JWT": tok})
    assert status == 200 and tenant == "tenantA"


def test_xtjwt_forged_rejected():
    tok = mint_token("tenantA", private_key_pem=PRIV, kid="k1", issuer=ISS, audience=AUD)
    # 按构造保证 forged != tok：旧写法固定换成 "zz"，签名末尾恰为 "zz" 时退化为原串
    # ⇒ 中间件给 200，属 1/4096（b64url 两位）概率假失败（docs/TODO.md 已登记）。
    forged = tok[:-2] + ("zz" if not tok.endswith("zz") else "zy")
    assert forged != tok, "伪造串与合法串相同 ⇒ 本用例没在校验签名，判据失效"
    tenant, status = _drive({"X-Tenant-JWT": forged})
    assert status == 401


def test_missing_xtjwt_observe_passthrough():
    # 无 X-Tenant-JWT → observe 透传，不绑定（下游见 api.context 默认 'default'，不破坏现有 API_KEY 链路）
    tenant, status = _drive({})
    assert status == 200 and tenant == "default"


def test_cooexists_with_opaque_api_key_bearer():
    # Authorization: Bearer <静态 API_KEY>（非 JWT）不影响：无 X-Tenant-JWT → 透传给既有鉴权
    tenant, status = _drive({"Authorization": "Bearer static-api-key"})
    assert status == 200 and tenant == "default"
