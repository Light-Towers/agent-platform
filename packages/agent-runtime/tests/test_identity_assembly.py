"""``mount_identity_gate`` 装配测试（roadmap 阶段2 #11，2026-10-16）。

分工：真实 FastAPI 上的挂载由 kefu/nl2sql 的应用级用例断言；本文件负责的是
「装配时传出去的那组 kwargs 跑起来是什么行为」——所以把假 app 记下来的入参**原样**喂给
纯 ASGI 中间件驱动，避免只测「调用过 add_middleware」而不测「接线正确」。

替身纪律：假 app 的 ``add_middleware(middleware_class, **kwargs)`` 签名与 FastAPI 一致，
不额外放宽也不额外收紧。env 一律经 monkeypatch fixture 保持到**请求发出之后**
（验签器按请求读 env，装配完就 undo 会测不到真实形状——本轮踩过）。
"""

from __future__ import annotations

import asyncio

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from agent_runtime.identity import mint_token, sign_internal_header, verify_internal_header
from agent_runtime.identity_assembly import (
    ENFORCE_ENV,
    FAILFAST_ENV,
    HMAC_KEY_ENV,
    mount_identity_gate,
    verify_internal_header_if_configured,
)
from agent_runtime.identity_middleware import IdentityMiddleware
from agent_runtime.workspace_registry import server_tenant_id

_IDENTITY_ENVS = (
    ENFORCE_ENV,
    FAILFAST_ENV,
    HMAC_KEY_ENV,
    "TENANT_JWT_PUBLIC_KEYS_FILE",
    "SINGLE_TENANT",
)

_prk = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIV = _prk.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()
HMAC_KEY = b"internal-hmac-key-shared-secret"


class _RecordingApp:
    """只记录装配入参的假 app（签名同 ``FastAPI.add_middleware``）。"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def add_middleware(self, middleware_class, *args, **kwargs) -> None:
        self.calls.append((middleware_class, args, kwargs))


def _assemble(monkeypatch: pytest.MonkeyPatch, **env: str | None) -> dict:
    """清掉身份相关 env 后按给定值装配，返回 {kwargs, snapshot}。

    env 由 fixture 持有，**不在装配后还原**——验签器按请求读 env。
    """
    app = _RecordingApp()
    for name in _IDENTITY_ENVS:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    snapshot = mount_identity_gate(app, "under-test")
    assert len(app.calls) == 1, f"装配点应只挂一层身份中间件，实际 {app.calls}"
    cls, _args, kwargs = app.calls[0]
    assert cls is IdentityMiddleware, "装配的必须是共享 IdentityMiddleware"
    return {"kwargs": kwargs, "snapshot": snapshot}


def _drive(middleware_kwargs: dict, headers: dict, path: str = "/x") -> tuple[object, int | None, str]:
    """纯 ASGI 驱动：返回 (下游看到的断言租户, 状态码, 响应体)。"""
    seen: dict = {}

    async def downstream(scope, receive, send):
        seen["tenant"] = server_tenant_id(default="<unbound>")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    mw = IdentityMiddleware(downstream, **middleware_kwargs)
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": b"",
        "scheme": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    sent: list = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        sent.append(msg)

    asyncio.run(mw(scope, receive, send))
    status = next((m["status"] for m in sent if m["type"] == "http.response.start"), None)
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body").decode()
    return seen.get("tenant"), status, body


def test_snapshot_defaults_to_observe_with_no_env(monkeypatch):
    """零 env（今日 kefu/nl2sql 的真实形状）⇒ observe 档 + 装配时密钥不在位。"""
    result = _assemble(monkeypatch)
    assert result["snapshot"] == {
        "tier": "observe",
        "startup_mode": "insecure",
        "hmac_key_present_at_assembly": False,
    }


def test_snapshot_reports_enforce_tier(monkeypatch):
    result = _assemble(monkeypatch, **{ENFORCE_ENV: "true"})
    assert result["snapshot"]["tier"] == "enforce", "档位必须如实反映 TENANT_JWT_ENFORCE"


def test_opaque_bearer_passes_through_unchanged(monkeypatch):
    """不透明 Bearer（静态 API_KEY 形态）不是本门卫的凭据 ⇒ 交下游，响应逐字不变。

    「接入即零行为变更」的正面证据：kefu/nl2sql 今日被网关调用时不带任何头，
    某些部署会带不透明 key，两种都必须原样通过。
    """
    kwargs = _assemble(monkeypatch)["kwargs"]
    tenant, status, body = _drive(kwargs, {"Authorization": "Bearer sk-some-opaque-api-key"})
    assert (status, body) == (200, "ok")
    assert tenant == "<unbound>", "observe 档不得替下游断言租户"


def test_no_credentials_passthrough(monkeypatch):
    kwargs = _assemble(monkeypatch)["kwargs"]
    tenant, status, body = _drive(kwargs, {})
    assert (status, body, tenant) == (200, "ok", "<unbound>")


def test_forged_internal_header_ignored_until_key_mounted(monkeypatch):
    """密钥不在位 ⇒ 伪造的内部头被忽略（而不是全量 401）。

    可用性护栏：网关一旦开始签发 ``X-Internal-Tenant`` 而子服务还没挂密钥，
    无条件采信会把该服务打成全量 401。
    """
    kwargs = _assemble(monkeypatch)["kwargs"]
    forged = sign_internal_header("attacker", key=b"some-other-key")
    tenant, status, body = _drive(kwargs, {"X-Internal-Tenant": forged})
    assert (status, body) == (200, "ok"), f"未配密钥时必须退回接入前行为，实际 {status} {body}"
    assert tenant == "<unbound>"


def test_signed_internal_header_asserts_tenant(monkeypatch, tmp_path):
    """配了密钥 ⇒ 合法签名头的租户进入服务端断言上下文（门卫真在做事，不是空挂）。"""
    key_file = tmp_path / "internal_hmac.key"
    key_file.write_bytes(HMAC_KEY)
    kwargs = _assemble(monkeypatch, **{HMAC_KEY_ENV: str(key_file)})["kwargs"]
    hdr = sign_internal_header("tenantA", "userB", key=HMAC_KEY)
    tenant, status, _body = _drive(kwargs, {"X-Internal-Tenant": hdr})
    assert status == 200
    assert tenant == "tenantA", "合法内部头必须覆盖成服务端断言租户"


def test_forged_internal_header_rejected_once_key_mounted(monkeypatch, tmp_path):
    key_file = tmp_path / "internal_hmac.key"
    key_file.write_bytes(b"the-real-key")
    kwargs = _assemble(monkeypatch, **{HMAC_KEY_ENV: str(key_file)})["kwargs"]
    forged = sign_internal_header("tenantA", key=b"the-wrong-key")
    _tenant, status, body = _drive(kwargs, {"X-Internal-Tenant": forged})
    assert status == 401, f"配了密钥后伪造内部头应 fail-closed，实际 {status} {body}"


def test_key_mounted_after_assembly_still_takes_effect(monkeypatch, tmp_path):
    """密钥是**装配之后**才挂上的 ⇒ 无需重启即开始采信（按请求判定的存在理由）。

    反向证据：若采信条件在装配时一次性固化，本用例拿到的是「忽略」＝200，
    运维就必须重启服务才能让门卫生效——那正是本函数要避免的形状。
    """
    kwargs = _assemble(monkeypatch)["kwargs"]  # 装配时密钥不在位
    key_file = tmp_path / "internal_hmac.key"
    key_file.write_bytes(HMAC_KEY)
    monkeypatch.setenv(HMAC_KEY_ENV, str(key_file))  # 事后挂上
    hdr = sign_internal_header("tenantLate", key=HMAC_KEY)
    tenant, status, _body = _drive(kwargs, {"X-Internal-Tenant": hdr})
    assert (status, tenant) == (200, "tenantLate"), "装配后补挂密钥必须立即开始断言"


def test_unverifiable_jwt_shape_is_401_not_passed_through(monkeypatch):
    """JWT 形态但服务端无验签公钥 ⇒ 401（身份声明不可验证时不采信，也不降级为匿名放行）。"""
    kwargs = _assemble(monkeypatch)["kwargs"]
    tok = mint_token("tenantA", private_key_pem=PRIV, kid="k1")
    _tenant, status, _body = _drive(kwargs, {"Authorization": f"Bearer {tok}"})
    assert status == 401, "JWT 形凭据不得在无法验签时静默通过"


def test_verifier_crash_fails_closed_without_leaking():
    """验签器自身异常（典型=镜像缺 PyJWT[crypto]）⇒ 401，不能变成 500，也不能回显异常文本。

    ``identity.py`` 的 ``import jwt`` 是惰性的：只有真收到令牌才 import，所以缺依赖只可能在
    这条路径上暴露。2026-10-16 之前它会被客户端触发成未捕获异常（可控输入→500）。
    """

    def _boom(_tok: str):
        raise ModuleNotFoundError("No module named 'jwt' —— 模拟镜像缺 [identity] extra")

    tenant, status, body = _drive(
        {"verify": _boom, "verify_header": None},
        {"Authorization": "Bearer eyJhbGciOiJSUzI1NiJ9.x.y"},
    )
    assert status == 401, f"验签器异常必须 fail-closed，实际 {status}"
    assert tenant is None, "异常路径不得进入下游"
    assert "jwt" not in body.lower() and "ModuleNotFoundError" not in body, f"异常文本不得回显：{body}"


def test_skip_paths_untouched(monkeypatch):
    """/health 在 skip 面内：带怪凭据也原样通过（就绪探针不能被门卫打断）。"""
    kwargs = _assemble(monkeypatch)["kwargs"]
    _tenant, status, _body = _drive(
        kwargs, {"Authorization": "Bearer eyJhbGciOiJSUzI1NiJ9.x.y"}, path="/health"
    )
    assert status == 200


def test_public_verifier_is_the_same_function_the_middleware_calls(monkeypatch, tmp_path):
    """装配传出的就是本模块那个按请求判定的函数（防止有人日后换成裸 verify_internal_header）。"""
    key_file = tmp_path / "internal_hmac.key"
    key_file.write_bytes(HMAC_KEY)
    kwargs = _assemble(monkeypatch, **{HMAC_KEY_ENV: str(key_file)})["kwargs"]
    assert kwargs["verify_header"] is verify_internal_header_if_configured
    hdr = sign_internal_header("tenantA", key=HMAC_KEY)
    assert verify_internal_header_if_configured(hdr) == verify_internal_header(hdr, key=HMAC_KEY)
    monkeypatch.delenv(HMAC_KEY_ENV)
    assert verify_internal_header_if_configured(hdr) is None, "撤掉密钥后应回到忽略"
