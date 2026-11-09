"""登录路由端到端判据（方案 plan-web-auth-user-minimal A2/A3/A5/D-f/§5）+ 一处真实拦下的配置矛盾。

为什么走**真实 app + 真实中间件**而不是裸路由单元：登录面的价值全在"签出去的令牌，这条
装配链验不验得回来"，把中间件换成 mock 就等于把这一格断言掉。本件里三处只有真链路能测：

1. 注册/登录后拿到的 Bearer 令牌，直接打到 `/auth/me` 必须 200 且回读到同一个 user（A4 的端到端面）；
2. **只有 ``user_id`` claim 的租户级令牌**在 `/auth/me` 必须 401 —— 这是 ``asserted_person_id``
   那条规则的实取，不是推定（成因见该函数 docstring：``verify_token`` 会把 ``sub`` 当 user）；
3. ``AUTH_TOKEN_TTL`` 超过 ``TENANT_JWT_MAX_TTL_S`` 时，登录必须当场 503 而不是"登录成功、
   下一个请求 401"（本轮实测出来的形状，见 ``test_overlong_ttl_is_rejected_at_login``）。

目录层（口令散列/NULL 拒绝/时间侧信道）在
``packages/agent-runtime/tests/test_auth_users.py``，本件把 ``create_user``/``verify_credentials``
换成桩：**路由层只测映射，不重复测目录**；需要真校验参与的那一格（登录名形状 → 400）用
一个不执行任何 SQL 的假池走真目录函数。
"""

from __future__ import annotations

import asyncio
import json

import pytest
from agent_runtime import auth_users as au
from agent_runtime.identity import mint_token
from agent_runtime.identity_middleware import IdentityMiddleware
from agent_server.api import auth_router
from agent_server.config import get_settings
from agent_server.main import _IDENTITY_SKIP_PATHS, app
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

LOGIN_OK = {"login": "alice", "password": "password123", "display_name": "Alice"}
ORG = "acme-test"
RECORD = au.UserRecord(id="alice", org_id=ORG, display_name="Alice", is_admin=True)

_prk = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIV = _prk.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()
PUB = _prk.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
).decode()


class _NoSqlPool:
    """假池：只用于"目录在碰库之前就拒绝"的路径（登录名/口令形状）。

    任何一条 SQL 被执行都是测试失败 —— 那意味着我以为在测入参校验，实际在测库交互。
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def connection(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                raise AssertionError(f"登录路由用例不应执行 SQL：{pool.calls}")

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


@pytest.fixture
def keys(tmp_path, monkeypatch):
    """密钥落临时文件 + env 指向它；公钥 JSON 的 kid 与 settings.tenant_jwt_kid 默认值同名。

    刻意不 monkeypatch ``auth_router.load_private_key`` —— 那两个函数是 env 驱动的，走 env
    才能顺带测出"私钥在位但公钥集里没有同一枚 kid"这类真实配置形状。
    """
    priv_file = tmp_path / "jwt.key"
    pubs_file = tmp_path / "jwt-pubs.json"
    priv_file.write_text(PRIV, encoding="utf-8")
    pubs_file.write_text(json.dumps({"platform": PUB}), encoding="utf-8")
    monkeypatch.setenv("TENANT_JWT_PRIVATE_KEY_FILE", str(priv_file))
    monkeypatch.setenv("TENANT_JWT_PUBLIC_KEYS_FILE", str(pubs_file))
    monkeypatch.delenv("TENANT_JWT_MAX_TTL_S", raising=False)
    monkeypatch.setenv("SIGNUP_ORG_ID", ORG)
    monkeypatch.setenv("SIGNUP_ENABLED", "true")
    monkeypatch.setenv("AUTH_TOKEN_TTL", "600")
    get_settings.cache_clear()
    yield {"priv": str(priv_file), "pubs": str(pubs_file), "dir": tmp_path}
    get_settings.cache_clear()


@pytest.fixture
def pool_stub(monkeypatch):
    """默认：有池 + 目录两个入口都换成桩（每格再单独改需要的行为）。"""
    pool = _NoSqlPool()
    monkeypatch.setattr(auth_router, "get_pool", lambda: pool)
    monkeypatch.setattr(auth_router, "create_user", _ok_create)
    monkeypatch.setattr(auth_router, "verify_credentials", _ok_verify)
    monkeypatch.setattr(auth_router, "touch_last_login", _noop_touch)
    return pool


async def _ok_create(pool, login, password, *, org_id, display_name="", is_admin=None):
    return RECORD


async def _ok_verify(pool, login, password):
    return RECORD


async def _noop_touch(pool, user_id):
    return None


def _client() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# A2 / A4：口令换令牌，且令牌立刻能用
# ---------------------------------------------------------------------------


def test_login_returns_bearer_token(pool_stub, keys):
    with _client() as client:
        resp = client.post("/auth/login", json=LOGIN_OK)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["tenant_id"] == ORG and body["user_id"] == "alice"
    assert body["is_admin"] is True
    assert body["expires_in"] == 600
    assert body["access_token"].count(".") == 2  # 三段式 JWS 形状


def test_login_token_is_accepted_by_the_real_middleware(pool_stub, keys):
    """A4 端到端面：登录拿到的令牌直接打 ``/auth/me``，服务端必须回读到同一个 user。

    这一格是"装配真的接上了"的唯一证据：路由单测里把中间件 mock 掉就永远测不到
    "验签通路的 env 与签发通路是否同一条"。
    """
    with _client() as client:
        token = client.post("/auth/login", json=LOGIN_OK).json()["access_token"]
        me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    assert me.json() == {"tenant_id": ORG, "user_id": "alice"}


def test_login_response_is_no_store(pool_stub, keys):
    with _client() as client:
        resp = client.post("/auth/login", json=LOGIN_OK)
    assert resp.headers["cache-control"] == "no-store"


def test_register_is_login_in_one_round_trip(pool_stub, keys):
    """用户原话"没有用户就在这个界面创建用户"⇒ 注册成功即等于已登录（201 + 可用令牌）。"""
    with _client() as client:
        resp = client.post("/auth/register", json=LOGIN_OK)
        assert resp.status_code == 201, resp.text
        token = resp.json()["access_token"]
        me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    assert me.json()["user_id"] == "alice"
    assert resp.headers["cache-control"] == "no-store"


def test_tenant_only_token_is_not_a_person(pool_stub, keys):
    """网关签发的**租户级令牌**（无 ``user_id`` claim）在 ``/auth/me`` 必须 401。

    不是"设计如此"的口头声明：``verify_token`` 会把 ``sub`` 当 user，而 ``mint_token`` 在无
    user 时写 ``sub = tenant_id`` ⇒ 中间件绑出来的"人"其实是租户名。若这里回 200，就等于
    我们自己把租户名说成用户 id，前端登录态显示的是企业名。
    """
    token = mint_token(ORG, private_key_pem=PRIV, kid="platform", ttl=600)
    with _client() as client:
        me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 401, me.text
    assert me.json()["code"] == auth_router.CODE_NOT_ASSERTED


def test_me_without_credential_is_401(keys):
    """``/auth/me`` 不接受任何客户端可指定的身份输入（它存在的意义就是证明断言发生过）。"""
    with _client() as client:
        me = client.get("/auth/me")
    assert me.status_code == 401, me.text
    assert me.json()["code"] == auth_router.CODE_NOT_ASSERTED


# ---------------------------------------------------------------------------
# A3：不泄露账号存在性
# ---------------------------------------------------------------------------


def test_wrong_password_and_unknown_user_return_identical_body(pool_stub, keys, monkeypatch):
    """A3 的逐字比对：两条分支的**整个响应体**必须相同（状态码 + code + msg）。

    目录对两者都返回 ``None``，路由因此无从区分 —— 这一格钉的是"将来有人想加一句
    '该用户不存在' 时必须先过本条"。
    """
    calls: list[str] = []

    async def _none(pool, login, password):
        calls.append(login)
        return None

    monkeypatch.setattr(auth_router, "verify_credentials", _none)
    with _client() as client:
        r_wrong = client.post("/auth/login", json={"login": "alice", "password": "bad-password"})
        r_missing = client.post("/auth/login", json={"login": "nosuchuser", "password": "bad-password"})
    assert r_wrong.status_code == 401 and r_missing.status_code == 401
    assert calls == ["alice", "nosuchuser"]
    assert r_wrong.json()["code"] == auth_router.CODE_CREDENTIALS_INVALID
    assert r_wrong.json()["msg"] == auth_router.CREDENTIALS_INVALID_MSG
    # 逐字相同（request_id 每条都不同 ⇒ 比的是去掉它之后的形状）
    a = {k: v for k, v in r_wrong.json().items() if k != "request_id"}
    b = {k: v for k, v in r_missing.json().items() if k != "request_id"}
    assert a == b


def test_null_password_hash_is_401_not_500(pool_stub, keys, monkeypatch):
    """A2 第三格：无口令账号（``password_hash IS NULL``）走同一条 401，不是 500。

    目录层的 NULL 判据在 test_auth_users 里钉；这里钉的是"它到 HTTP 面上仍是一个 401"。
    """
    monkeypatch.setattr(auth_router, "verify_credentials", _none_credentials)
    with _client() as client:
        resp = client.post("/auth/login", json=LOGIN_OK)
    assert resp.status_code == 401, resp.text
    assert resp.json()["code"] == auth_router.CODE_CREDENTIALS_INVALID


async def _none_credentials(pool, login, password):
    return None


# ---------------------------------------------------------------------------
# 输入与开关
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("login", ["ab", "a" * 33, "Alice!", "a b", "a/b"])
def test_bad_login_shape_is_400_with_directory_hint(keys, monkeypatch, login):
    """400 的文案取自目录常量（单一实现），且**不执行任何 SQL**。

    这一格走真 ``create_user``（假池只保证不碰库）：入参校验发生在取连接之前，所以池一旦被
    使用，``_NoSqlPool`` 就抛 ⇒ 测的是校验顺序，不只是状态码。
    """
    pool = _NoSqlPool()
    monkeypatch.setattr(auth_router, "get_pool", lambda: pool)
    with _client() as client:
        resp = client.post("/auth/register", json={"login": login, "password": "password123"})
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == auth_router.CODE_INPUT_INVALID
    assert resp.json()["msg"] == au.LOGIN_SHAPE_HINT


@pytest.mark.parametrize("pw", ["short", "a" * 200])
def test_bad_password_band_is_400_with_directory_hint(keys, monkeypatch, pw):
    """同上，另一类入参：长度带。文案同样取自目录常量，不在路由侧重写一句。"""
    pool = _NoSqlPool()
    monkeypatch.setattr(auth_router, "get_pool", lambda: pool)
    with _client() as client:
        resp = client.post("/auth/register", json={"login": "alice", "password": pw})
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == auth_router.CODE_INPUT_INVALID
    assert resp.json()["msg"] == au.PASSWORD_LENGTH_HINT


def test_signup_disabled_returns_403(pool_stub, keys, monkeypatch):
    monkeypatch.setenv("SIGNUP_ENABLED", "false")
    get_settings.cache_clear()
    with _client() as client:
        resp = client.post("/auth/register", json=LOGIN_OK)
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == auth_router.CODE_SIGNUP_DISABLED
    # 注册关不掉登录（D-f 只关自助注册面）
    with _client() as client:
        assert client.post("/auth/login", json=LOGIN_OK).status_code == 200


def test_duplicate_login_is_409(pool_stub, keys, monkeypatch):
    async def _dup(pool, login, password, *, org_id, display_name="", is_admin=None):
        raise au.UserExistsError(login)

    monkeypatch.setattr(auth_router, "create_user", _dup)
    with _client() as client:
        resp = client.post("/auth/register", json=LOGIN_OK)
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == auth_router.CODE_LOGIN_TAKEN


# ---------------------------------------------------------------------------
# 配置未就位 ⇒ 503 + 稳定 code（不是 500、也不是"凭据不对"）
# ---------------------------------------------------------------------------


def test_no_pool_is_503_not_degraded_to_key(keys, monkeypatch):
    """内存模式（无 DATABASE_URL）下登录整体不可用，**不静默退化成"用静态 key 也能玩"**。"""
    monkeypatch.setattr(auth_router, "get_pool", lambda: None)
    with _client() as client:
        resp = client.post("/auth/login", json=LOGIN_OK)
    assert resp.status_code == 503, resp.text
    assert resp.json()["code"] == auth_router.CODE_STORE_UNAVAILABLE


def test_missing_private_key_is_503_signer(keys, monkeypatch, pool_stub):
    monkeypatch.setenv("TENANT_JWT_PRIVATE_KEY_FILE", str(keys["dir"] / "absent.key"))
    get_settings.cache_clear()
    with _client() as client:
        resp = client.post("/auth/login", json=LOGIN_OK)
    assert resp.status_code == 503, resp.text
    assert resp.json()["code"] == auth_router.CODE_SIGNER_UNAVAILABLE


def test_private_key_without_matching_pubkid_is_503_at_login(keys, monkeypatch, pool_stub):
    """私钥在位但公钥集里没有同名 kid ⇒ 登录就 503，不放行到"下一个请求 401"。

    成因写在 ``_signer_or_503`` 里：``verify_token`` 按 header kid 选公钥且不逐把试。
    """
    (keys["dir"] / "jwt-pubs.json").write_text(json.dumps({"other": PUB}), encoding="utf-8")
    with _client() as client:
        resp = client.post("/auth/login", json=LOGIN_OK)
    assert resp.status_code == 503, resp.text
    assert resp.json()["code"] == auth_router.CODE_SIGNER_UNAVAILABLE


def test_overlong_ttl_is_rejected_at_login_not_next_request(keys, monkeypatch, pool_stub):
    """D-j 的 8h 与 ``TENANT_JWT_MAX_TTL_S``（默认 3600）冲突 ⇒ 登录当场 503。

    本轮实测出来的形状（取证件 k48-ttl-probe：``ttl=28800 → 令牌 TTL 28800s 超上限 3600s``）：
    没有签发后自验时，症状是"登录成功、下一个请求 401"，看起来像口令错，排查会走错方向。
    把 AUTH_TOKEN_TTL 与 TENANT_JWT_MAX_TTL_S **同时**抬到 7200 才许登录成功 —— 这也正是
    部署清单里那两把键必须成对修改的原因。
    """
    monkeypatch.setenv("AUTH_TOKEN_TTL", "28800")
    get_settings.cache_clear()
    with _client() as client:
        resp = client.post("/auth/login", json=LOGIN_OK)
        assert resp.status_code == 503, resp.text
        assert resp.json()["code"] == auth_router.CODE_SIGNER_UNAVAILABLE
        # 两边同时抬 ⇒ 通过
        monkeypatch.setenv("TENANT_JWT_MAX_TTL_S", "7200")
        monkeypatch.setenv("AUTH_TOKEN_TTL", "7200")
        get_settings.cache_clear()
        assert client.post("/auth/login", json=LOGIN_OK).status_code == 200


# ---------------------------------------------------------------------------
# A5：enforce 档下登录自己必须能通
# ---------------------------------------------------------------------------


def _drive_middleware(path: str, headers: dict[str, str], **mw_kwargs) -> tuple[bool, int | None]:
    """纯 ASGI 驱动中间件，返回 (下游是否被调用, 状态码)。"""
    seen: dict[str, bool] = {}

    async def downstream(scope, receive, send):
        seen["reached"] = True
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    mw = IdentityMiddleware(downstream, **mw_kwargs)
    scope = {
        "type": "http",
        "method": "POST",
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
    return seen.get("reached", False), status


def test_enforce_mode_still_allows_login_and_blocks_others(keys):
    """A5：``TENANT_JWT_ENFORCE=true`` 下 ``/auth/login``、``/auth/register`` 仍可通，其余 401。

    忘传 ``skip_paths`` 的形状是"登录接口自己 401，永远登不进去"，而且只在 enforce 档出现
    ⇒ 观察档跑绿的套件抓不到，所以这条必须显式钉 enforce_missing=True。
    """
    common = {"skip_paths": _IDENTITY_SKIP_PATHS, "enforce_missing": True, "single_tenant": None}
    reached_login, status_login = _drive_middleware("/auth/login", {}, **common)
    reached_register, status_register = _drive_middleware("/auth/register", {}, **common)
    reached_query, status_query = _drive_middleware("/query", {}, **common)
    assert (reached_login, status_login) == (True, 204), "登录被门卫拦下 ⇒ skip_paths 漏传"
    assert (reached_register, status_register) == (True, 204)
    assert (reached_query, status_query) == (False, 401)


def test_skip_paths_is_superset_of_middleware_default():
    """本件的 skip 集必须**包含**中间件构造默认集，否则"顺手改掉 /health 免检"会静默发生。

    两处默认集不一致时不会报错，只会让探针在 observe 档能用、enforce 档登不进（与 A5 同一族
    的失效形状），所以拿代码里的默认值反比对一次。
    """
    import inspect

    default = inspect.signature(IdentityMiddleware.__init__).parameters["skip_paths"].default
    assert set(default) <= set(_IDENTITY_SKIP_PATHS), set(default) - set(_IDENTITY_SKIP_PATHS)
    assert {"/auth/login", "/auth/register"} <= set(_IDENTITY_SKIP_PATHS)


# ---------------------------------------------------------------------------
# 登出的如实陈述
# ---------------------------------------------------------------------------


def test_logout_declares_it_does_not_revoke(pool_stub, keys):
    """撤销属 PR-3：本端点必须自己说清"没撤销"，不能让 200 被读成"令牌已失效"。"""
    with _client() as client:
        token = client.post("/auth/login", json=LOGIN_OK).json()["access_token"]
        out = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
        assert out.status_code == 200, out.text
        assert out.json() == {"status": "logged_out", "revoked": "false"}
        assert out.headers["cache-control"] == "no-store"
        # 令牌在 exp 前依然可用（这条断言就是"撤销未具备"的证据，别当已具备写）
        assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200
