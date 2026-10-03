"""B7b-4 接线序 + 401 优先级（联邦网关 identity ⇄ guards）。

锁两件事，缺一不可：

1. **真源接线序**（AST，不依赖导入 ``api.server``）：``SecurityGuardsMiddleware`` 的注册必须
   早于 ``mount_identity_middleware(app)``。Starlette 的 ``add_middleware`` 是
   ``user_middleware.insert(0, ...)`` ⇒ 列表里**越靠前越外层**，即「后注册者更外层」。
   旧代码把 identity 挂在 guards 之前 ⇒ guards 跑在身份之前，限流取主体时租户尚未绑定，
   ``subject_provider`` 实质始终退回客户端 IP（B7b-2 §4.2 补记第 3 条登记的中间态）。
   用 AST 而非 ``import api.server`` 检查：后者会 ``from agent.main_agent import run_deep_agent``
   触发 model 构造，且中间件装配取决于**模块导入时**的 ``API_KEY`` env（本机环境会漂移，
   CI 上未配 ⇒ guards 根本没注册 ⇒ 断言无从谈起）。同理断言 guards 的
   ``subject_provider=get_asserted_tenant_context``（而非 ``get_tenant_context``，后者把
   「从未断言」也读成 ``default``，会把所有未断言请求并成一个主体桶）。

2. **行为侧 401 优先级**（plan A-4 要求的双向用例）：伪造/过期 ``X-Tenant-JWT`` 的 401
   从此抢在 API-Key 401 之前（身份断言优先于传输鉴权，与 ADR-0007 信任链一致）；反向
   「合法租户 JWT + 错误 API_KEY」仍由 guards 出 401，身份层不越权放行。
   另附**反例用例**证明优先级差异确实由接线序造成（旧序下 identity 的 401 会被吞）。

主体绑定用真实链路：``mount_identity_middleware``（不注入 verify 替身）+ 临时 RSA 密钥对 +
``TENANT_JWT_PUBLIC_KEYS_FILE`` ⇒ 走的是生产同款 ``verify_token``。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from agent_core.guardrails.web import SecurityGuardsMiddleware
from agent_runtime.identity import mint_token  # noqa: I001 - 第三方（cryptography）依赖紧随其后
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.context import get_asserted_tenant_context
from api.identity_bridge import mount_identity_middleware

_SERVER_PY = Path(__file__).resolve().parents[2] / "api" / "server.py"

_GUARD_KEY = "dGVzdC1hcGkta2V5LWZvci1vcmRlci10ZXN0"  # 仅测试用固定值，非真实凭据


# ---------------------------------------------------------------------------
# 1) 真源接线序（AST 语义门禁）
# ---------------------------------------------------------------------------


def _collect_registrations() -> dict[str, list[ast.Call]]:
    """扫描 server.py，收集 guards 注册调用与 identity 挂载调用（按出现顺序）。"""
    tree = ast.parse(_SERVER_PY.read_text(encoding="utf-8"), filename=str(_SERVER_PY))
    guards: list[ast.Call] = []
    identity: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # app.add_middleware(SecurityGuardsMiddleware, ...)
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "add_middleware"
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "SecurityGuardsMiddleware"
        ):
            guards.append(node)
        # mount_identity_middleware(app)
        elif isinstance(func, ast.Name) and func.id == "mount_identity_middleware":
            identity.append(node)
    assert guards, "server.py 未注册 SecurityGuardsMiddleware，判据失效（请核对改动）"
    assert identity, "server.py 未挂载 mount_identity_middleware，判据失效（请核对改动）"
    return {"guards": guards, "identity": identity}


def test_identity_middleware_registered_after_guards():
    """后注册 = 更外层 ⇒ identity 必须写在 guards 之后，才能先绑定主体再进 guards。"""
    regs = _collect_registrations()
    guards_lineno = regs["guards"][0].lineno
    identity_lineno = regs["identity"][0].lineno
    assert identity_lineno > guards_lineno, (
        f"接线序回退：identity 挂载（L{identity_lineno}）又跑到 guards 注册（L{guards_lineno}）之前，"
        "限流桶会退回客户端 IP（B7b-2 §4.2 补记第 3 条）"
    )


def test_guards_use_asserted_tenant_subject_provider():
    """guards 的 ``subject_provider`` 必须是 asserted 版（无断言返 None，而不是 'default'）。"""
    regs = _collect_registrations()
    kwargs = {kw.arg: kw.value for kw in regs["guards"][0].keywords if kw.arg}
    assert "subject_provider" in kwargs, "guards 未注入 subject_provider ⇒ 限流桶退回 IP"
    provider = kwargs["subject_provider"]
    assert isinstance(provider, ast.Name), "subject_provider 应为具名回调，便于静态判定"
    assert provider.id == "get_asserted_tenant_context", (
        f"subject_provider={provider.id}：必须用 get_asserted_tenant_context，"
        "get_tenant_context 会把「从未断言」读成 default 租户，与主体化语义冲突"
    )


# ---------------------------------------------------------------------------
# 2) 行为侧：401 优先级（新序 + 旧序反例）
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def issuer_keys(tmp_path_factory):
    """真实 RSA 密钥对 + 公钥 JSON 文件，并把验签配置注入环境（模块级，避免重复生成）。"""
    prk = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = prk.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    pub = prk.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    keys_file = tmp_path_factory.mktemp("issuer") / "keys.json"
    keys_file.write_text(json.dumps({"k1": pub}), encoding="utf-8")
    return priv, str(keys_file)


def _valid_token(priv: str) -> str:
    return mint_token("tenantA", user_id="u1", private_key_pem=priv, kid="k1")


def _forged_token(priv: str) -> str:
    tok = _valid_token(priv)
    return tok[:-2] + "zz"


def _build_app(*, identity_first: bool = False, seen_subjects: list | None = None) -> FastAPI:
    """按生产接线序装配 mini app（guards ⇄ identity），路由只做回显，不碰 agent。"""
    app = FastAPI()

    @app.post("/invoke")
    def invoke() -> dict:  # pragma: no cover - 仅用于验证是否进入路由
        return {"ok": True}

    def _provider() -> str | None:
        value = get_asserted_tenant_context()
        if seen_subjects is not None:
            seen_subjects.append(value)
        return value

    guards = dict(
        api_key=_GUARD_KEY,
        rate_limit_per_client=1000,
        rate_limit_global=10000,
        subject_provider=_provider,
    )
    if identity_first:  # 旧接线序（反例）
        mount_identity_middleware(app)
        app.add_middleware(SecurityGuardsMiddleware, **guards)
    else:  # 新接线序（与 server.py 一致）
        app.add_middleware(SecurityGuardsMiddleware, **guards)
        mount_identity_middleware(app)
    return app


def _post(app: FastAPI, headers: dict):
    with TestClient(app) as client:
        return client.post("/invoke", headers=headers)


def _auth_headers(token: str | None = None, *, api_key: str = _GUARD_KEY) -> dict:
    headers = {"Authorization": f"Bearer {api_key}"}
    if token:
        headers["X-Tenant-JWT"] = token
    return headers


@pytest.fixture(autouse=True)
def _identity_env(issuer_keys, monkeypatch):
    """只影响本文件的用例：验签公钥就位、无 SINGLE_TENANT、未开 enforce（observe）。"""
    _priv, keys_file = issuer_keys
    monkeypatch.setenv("TENANT_JWT_PUBLIC_KEYS_FILE", keys_file)
    monkeypatch.delenv("TENANT_JWT_ISSUER", raising=False)
    monkeypatch.delenv("TENANT_JWT_AUDIENCE", raising=False)
    monkeypatch.delenv("SINGLE_TENANT", raising=False)
    monkeypatch.delenv("DEPLOY_ENFORCE_IDENTITY", raising=False)
    monkeypatch.delenv("TENANT_JWT_ENFORCE", raising=False)


def test_forged_jwt_and_wrong_key_identity_401_wins(issuer_keys):
    """两侧凭据都非法时，新序下 401 由**身份层**出（接线序对调真正引入的行为变更）。

    这是唯一能区分两种接线序的组合：若只把 API_KEY 配对，旧序下 identity（更内层）
    同样会拒，看不出差异 ⇒ 本用例与旧序反例均带上错误 API_KEY。
    """
    priv, _ = issuer_keys
    resp = _post(_build_app(), _auth_headers(_forged_token(priv), api_key="wrong-key"))
    assert resp.status_code == 401
    body = resp.json()
    # guards 的错误信封是 {"code": "UNAUTHORIZED", ...}；身份层是 {"detail": "身份令牌无效: ..."}
    assert "code" not in body, f"401 竟由 guards 出（接线序回退？）：{body}"
    assert "身份令牌无效" in body["detail"]


def test_forged_jwt_with_correct_api_key_still_identity_401(issuer_keys):
    """伪造租户令牌不因 API_KEY 正确而放行：断言失败即拒（防「传输凭据对了就信租户」）。"""
    priv, _ = issuer_keys
    resp = _post(_build_app(), _auth_headers(_forged_token(priv)))
    assert resp.status_code == 401
    assert "身份令牌无效" in resp.json()["detail"]


def test_valid_jwt_wrong_api_key_still_guard_401(issuer_keys):
    """反向：合法租户 JWT + 错误 API_KEY ⇒ 401 仍由 guards 出，身份断言不越权放行。"""
    priv, _ = issuer_keys
    resp = _post(_build_app(), _auth_headers(_valid_token(priv), api_key="wrong-key"))
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHORIZED"


def test_valid_jwt_and_key_pass_with_subject_bound_before_guards(issuer_keys):
    """两层都通过时，guards 读到的主体已是 identity 绑定的断言租户（B7b-2 中间态已闭合）。"""
    priv, _ = issuer_keys
    seen: list = []
    resp = _post(_build_app(seen_subjects=seen), _auth_headers(_valid_token(priv)))
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert seen == ["tenantA"], f"guards 未看到已断言主体（退回 IP 桶）：{seen}"


def test_old_order_wrong_credentials_guard_401_wins(issuer_keys):
    """反例（证明优先级断言真由接线序决定、不是巧合）：旧序下同一请求由 guards 出 401。

    本用例**不为旧序背书**：一旦有人把 ``mount_identity_middleware`` 挪回 guards 之前，
    ``test_forged_jwt_and_wrong_key_identity_401_wins`` 会红，而本用例仍绿（它锁的就是旧序行为）。
    """
    priv, _ = issuer_keys
    resp = _post(
        _build_app(identity_first=True), _auth_headers(_forged_token(priv), api_key="wrong-key")
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHORIZED"


def test_old_order_guards_fall_back_to_ip_bucket(issuer_keys):
    """反例：旧序下 guards 求主体时租户尚未绑定 ⇒ 限流桶实质退回客户端 IP（B7b-2 登记的中间态）。"""
    priv, _ = issuer_keys
    seen: list = []
    resp = _post(
        _build_app(identity_first=True, seen_subjects=seen), _auth_headers(_valid_token(priv))
    )
    assert resp.status_code == 200
    assert seen == [None], f"旧序应表现为「主体未绑定→退 IP」，用于证明上条用例的判据来自接线序：{seen}"
