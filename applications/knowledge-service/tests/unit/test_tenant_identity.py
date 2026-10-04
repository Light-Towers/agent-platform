"""knowledge-service 侧内部签名头租户断言测试（ADR-0007 决策1=A3）。

- resolve_server_tenant：签名断言 > provided > default 优先级；
- TenantHeaderMiddleware：合法头绑定、伪造头 401、缺头透传、未配密钥忽略头。
纯 ASGI 驱动 + tmp_path 密钥文件，无 DB / 无网络。
"""

from __future__ import annotations

import asyncio

from agent_core.internal_header import sign_internal_header

from knowledge_service.core.config import settings
from knowledge_service.utils.tenant_identity import (
    TenantHeaderMiddleware,
    bind_asserted_tenant,
    current_asserted_tenant,
    reset_asserted_tenant,
)
from knowledge_service.utils.tenant_utils import resolve_server_tenant

KEY = b"ks-shared-hmac-secret-key"


def test_resolve_prefers_signed_assertion_over_provided():
    token = bind_asserted_tenant("tenantA")
    try:
        # body 传 EVIL 也应被签名断言覆盖
        assert resolve_server_tenant("EVIL", endpoint="/query") == "tenantA"
    finally:
        reset_asserted_tenant(token)


def test_resolve_uses_provided_when_no_assertion():
    assert current_asserted_tenant() is None
    assert resolve_server_tenant("tenantB", endpoint="/x") == "tenantB"


def test_resolve_default_when_neither():
    assert resolve_server_tenant("", endpoint="/x") == (settings.knowledge_default_tenant_id or "default")


def _drive(mw_kwargs, headers):
    seen: dict = {}

    async def downstream(scope, receive, send):
        seen["asserted"] = current_asserted_tenant()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    mw = TenantHeaderMiddleware(downstream, **mw_kwargs)
    scope = {
        "type": "http", "method": "POST", "path": "/query", "scheme": "http", "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    sent: list = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        sent.append(msg)

    asyncio.run(mw(scope, receive, send))
    status = next((m["status"] for m in sent if m["type"] == "http.response.start"), None)
    return seen.get("asserted"), status


def _set_key(monkeypatch, tmp_path):
    kf = tmp_path / "hmac.key"
    kf.write_bytes(KEY)
    monkeypatch.setenv("INTERNAL_HMAC_KEY_FILE", str(kf))


def test_mw_valid_header_binds_assertion(monkeypatch, tmp_path):
    _set_key(monkeypatch, tmp_path)
    hdr = sign_internal_header("tenantA", "userB", key=KEY)
    asserted, status = _drive({}, {"X-Internal-Tenant": hdr})
    assert status == 200 and asserted == "tenantA"


def test_mw_forged_header_rejected(monkeypatch, tmp_path):
    _set_key(monkeypatch, tmp_path)
    hdr = sign_internal_header("tenantA", None, key=KEY)
    # 按构造保证 forged != hdr：旧写法固定换成 "ff"，真签名末尾恰为 "ff" 时退化为原串
    # ⇒ 中间件给 200，属 1/256 概率假失败（与 agent-core 同构，docs/TODO.md 已登记）。
    tail = "11" if hdr.endswith("00") else "00"
    forged = hdr[:-2] + tail
    assert forged != hdr, "伪造串与合法串相同 ⇒ 本用例没在校验签名，判据失效"
    asserted, status = _drive({}, {"X-Internal-Tenant": forged})
    assert status == 401


def test_mw_missing_header_passthrough(monkeypatch, tmp_path):
    _set_key(monkeypatch, tmp_path)
    asserted, status = _drive({"enforce_missing": False}, {})
    assert status == 200 and asserted is None


def test_mw_no_key_configured_ignores_header(monkeypatch):
    monkeypatch.delenv("INTERNAL_HMAC_KEY_FILE", raising=False)
    hdr = sign_internal_header("tenantA", None, key=KEY)
    # 未配密钥（开发态）→ 无法校验 → 透传不绑定（不误信裸头）
    asserted, status = _drive({}, {"X-Internal-Tenant": hdr})
    assert status == 200 and asserted is None


def test_mw_enforce_missing_rejects_anonymous(monkeypatch, tmp_path):
    _set_key(monkeypatch, tmp_path)
    asserted, status = _drive({"enforce_missing": True}, {})
    assert status == 401
