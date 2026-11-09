# -*- coding: utf-8 -*-
"""登录面 HTTP 端点：``/auth/register``、``/auth/login``、``/auth/me``、``/auth/logout``。

方案 docs/plans/plan-web-auth-user-minimal-2026-11-05.md 的 D-a/D-j/§5 落在本件。薄封装层：
口令怎么散列、账号怎么归一化全在 :mod:`agent_runtime.auth_users`（单一实现），令牌怎么签
全在 :mod:`agent_runtime.identity`（与网关同一条 RS256 通路）。本件只做四件事：
取连接池 → 调目录 → 签令牌 → 把错误映射成统一信封里的稳定 code。

错误出口一律走 ``AppError``（由 ``build_api_app`` 安装的 handler 渲染成
``{code,msg,request_id}``），不在这里手写 JSONResponse —— 手写就绕过了 request_id/X-Trace-Id
那套管道，前端也就拿不到可引用的请求号。

⚠ 5xx 的 ``msg`` **不会**是这里写的这句：kernel handler 对 ``status_code >= 500`` 强制
脱敏成固定文案（``agent_core.guardrails.errors.app_error_handler``），只有 ``code`` 传得出去。
这是有意的（内部配置细节不给未鉴权的一端看），所以真因一律进服务端日志；读到
``AUTH_SIGNER_UNAVAILABLE`` 的人请查日志而不是要求把 msg 改回可读——那等于把脱敏面打开。

凭据外流的三条硬约束（A7，对应 ``tests/governance/test_login_no_secret_leakage.py``）：
1. 口令不进日志：本件不打任何含请求体字段的日志行；
2. 散列不进响应：``UserRecord`` 结构上就没有 ``password_hash`` 字段（见 auth_users 注释）；
3. 令牌只出现在**它自己的那次响应**里，不进日志、不进错误 msg。
"""

from __future__ import annotations

import logging

from agent_core.guardrails.errors import AppError
from agent_runtime.auth_users import (
    LOGIN_SHAPE_HINT,
    PASSWORD_LENGTH_HINT,
    AuthStoreUnavailable,
    InvalidLogin,
    InvalidPassword,
    UserExistsError,
    create_user,
    normalize_login,
    touch_last_login,
    verify_credentials,
)
from agent_runtime.db import get_pool
from agent_runtime.identity import (
    IdentityError,
    load_private_key,
    load_public_keys,
    mint_token,
    verify_token,
)
from agent_runtime.workspace_registry import asserted_person_id, asserted_tenant_id
from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from agent_server.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()

# 对外稳定错误码（前端按 code 分支，不按 msg 文案分支）。
CODE_CREDENTIALS_INVALID = "AUTH_CREDENTIALS_INVALID"
CODE_SIGNER_UNAVAILABLE = "AUTH_SIGNER_UNAVAILABLE"
CODE_STORE_UNAVAILABLE = "AUTH_STORE_UNAVAILABLE"
CODE_SIGNUP_DISABLED = "SIGNUP_DISABLED"
CODE_LOGIN_TAKEN = "AUTH_LOGIN_TAKEN"
CODE_INPUT_INVALID = "AUTH_INPUT_INVALID"
CODE_NOT_ASSERTED = "AUTH_NOT_ASSERTED"

# 口令校验失败的**唯一**文案：账号不存在与口令错共用一句（A3）。
# 这句一旦分叉就等于告诉未鉴权的一端"这个账号存在吗"，所以比对在目录里做，文案在这里只留一份。
CREDENTIALS_INVALID_MSG = "登录名或口令不正确"


class LoginRequest(BaseModel):
    """``/auth/login`` 与 ``/auth/register`` 共用的入参形状（口令只在服务端做散列比对）。"""

    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    display_name: str = Field(default="", max_length=64)


class TokenResponse(BaseModel):
    """登录/注册的成功响应。``token_type`` 恒为 ``bearer``（写死而不是默认值：前端拼
    ``Authorization`` 头时依赖它，留成可覆盖的默认就等于给将来留一个"改了没人知道"的口子）。"""

    token_type: str = "bearer"
    access_token: str
    expires_in: int
    tenant_id: str
    user_id: str
    is_admin: bool


class MeResponse(BaseModel):
    tenant_id: str
    user_id: str


def _pool_or_503():
    pool = get_pool()
    if pool is None:
        # 内存模式没有 users 表 ⇒ 登录面整体不可用。这是**配置状态**而不是凭据问题，
        # 所以是 503 + 固定 code，不静默退化成"用静态 key 也能玩"（方案 §5.4）。
        logger.warning("登录面不可用：DATABASE_URL 未配置（内存模式无 users 表）")
        raise AppError(503, CODE_STORE_UNAVAILABLE, "登录未启用：用户目录不可用")
    return pool


def _signer_or_503() -> tuple[str, str]:
    """取签发私钥 + kid，并**前置校验**公钥集里有同一枚 kid。

    为什么要在签之前查公钥：``verify_token`` 按 header kid 选公钥、对不上直接拒
    （``identity.py`` 明写"不逐把试密钥"）。只配了私钥没配公钥（或两边 kid 拼写不一致）
    时，签出去的令牌自己验不回来 —— 症状是"登录成功、下一个请求 401"，比现在这里
    报 503 难查一个量级。
    """
    settings = get_settings()
    kid = settings.tenant_jwt_kid.strip()
    private_key_pem = load_private_key()
    if not private_key_pem or not kid:
        logger.warning("登录面不可用：TENANT_JWT_PRIVATE_KEY_FILE 未挂载或 TENANT_JWT_KID 未配")
        raise AppError(503, CODE_SIGNER_UNAVAILABLE, "登录未启用：签名密钥未在位")
    keys = load_public_keys()
    if kid not in keys:
        logger.warning(
            "私钥在位但验签公钥集里没有 kid=%r（现有 %s）⇒ 签出的令牌会当场验不回来，按未启用处理",
            kid,
            sorted(keys) or "（空）",
        )
        raise AppError(503, CODE_SIGNER_UNAVAILABLE, "登录未启用：签名密钥配置不完整")
    return private_key_pem, kid


def _issue(user_id: str, tenant_id: str, private_key_pem: str, kid: str) -> str:
    """签 RS256 登录令牌（复用 ``identity.mint_token``，不另造一套 claim 形状），**签完自验一次**。

    为什么要多花一次验签（RSA 公钥验是微秒级）：``mint_token`` 与 ``verify_token`` 是两个人写的
    函数，它们之间的约定全靠参数：寿命上限（``TENANT_JWT_MAX_TTL_S`` 默认 3600，本轮实测
    ``AUTH_TOKEN_TTL=28800`` 签出的令牌被当场拒）、iss/aud 默认值、kid 名字。任何一边漂了，
    没自验的形状都是「登录 200 拿了令牌、下一个请求 401」——隔一次往返才暴露、而且看起来像
    口令错。自验把同一颗错提前到登录那一次往返里，以 503 + 固定 code 暴露。

    ``jwt`` 是惰性导入：镜像没装 ``[identity]`` 时这里才炸。那是一条**配置错误**不是
    代码错误，所以转成 503（与中间件那侧的 fail-closed 401 分工不同：那边是“收到的令牌
    验不了”，这边是“我根本发不出令牌”）。
    """
    settings = get_settings()
    try:
        token = mint_token(
            tenant_id,
            user_id=user_id,
            private_key_pem=private_key_pem,
            kid=kid,
            ttl=settings.auth_token_ttl,
        )
    except IdentityError:
        raise
    except Exception as e:  # 只兜依赖缺失一型（惰性导入），其余照外走
        if not isinstance(e, ModuleNotFoundError):
            raise
        logger.exception("签发登录令牌失败：镜像缺 PyJWT[crypto]（agent-runtime[identity]）")
        raise AppError(503, CODE_SIGNER_UNAVAILABLE, "登录未启用：签名依赖缺失") from e

    # 自验：用与中间件完全同一条验签通路（不传任何参数 ⇒ 两边读同一套 env）。
    try:
        verify_token(token)
    except IdentityError as e:
        # 真因只进日志（5xx 的 msg 会被 kernel 强制脱敏），但这条必须可读：
        # 能走到这里就是部署配置自相矛盾，文案里点到具体键名比只报“不可用”省一轮排查。
        logger.error(
            "签出的登录令牌无法自验（kid=%s ttl=%ss）：%s ⇒ 请同时校 AUTH_TOKEN_TTL 与 "
            "TENANT_JWT_MAX_TTL_S / TENANT_JWT_PUBLIC_KEYS_FILE",
            kid,
            settings.auth_token_ttl,
            e,
        )
        raise AppError(503, CODE_SIGNER_UNAVAILABLE, "登录未启用：签发参数与验签参数不一致") from e
    return token


def _map_input_error(exc: ValueError) -> AppError:
    """入参形状错误 → 400 + 固定文案。

    不把异常携带的文本直接当对外 ``msg``：P8 不变量禁止对外响应体回显异常消息（它不区分
    异常里装的是我自己写的文案还是库的文本，从语法上封死这一形），而“把异常文本当响应”这个
    口子一开，下一次就有人往里放库报错。
    文案取自目录的常量（单一实现），不是这边重新写一句——两处文案分叉就等于前端按哪句做
    分支都不对。按类型分派：本函数只接两类，第三类进到这里也是调用点写错，宁可当场
    TypeError 也不要默默给一条错的提示。
    """
    if isinstance(exc, InvalidPassword):
        return AppError(400, CODE_INPUT_INVALID, PASSWORD_LENGTH_HINT)
    if isinstance(exc, InvalidLogin):
        return AppError(400, CODE_INPUT_INVALID, LOGIN_SHAPE_HINT)
    raise TypeError(f"_map_input_error 只接 InvalidLogin/InvalidPassword，收到 {type(exc).__name__}")


@router.post("/auth/register", response_model=TokenResponse, status_code=201)
async def register(body: LoginRequest, response: Response) -> TokenResponse:
    """自助注册并**直接登录**（一次往返拿到令牌：用户的原话是"没有用户就在这个界面创建用户"，
    所以注册成功即等于已登录，不需要再点一次"登录"）。

    ``SIGNUP_ENABLED=false`` 时 403 关掉整面（D-f）；此时"完整产品"退化成管理员建号，
    这一档必须存在，否则内网之外暴露时没人能拦。
    """
    settings = get_settings()
    if not settings.signup_enabled:
        raise AppError(403, CODE_SIGNUP_DISABLED, "自助注册已关闭（SIGNUP_ENABLED=false）")
    org_id = settings.signup_effective_org_id
    if not org_id:
        logger.warning("注册落点 org 为空（SIGNUP_ORG_ID 与 DEFAULT_TENANT_ID 都没配）")
        raise AppError(503, CODE_STORE_UNAVAILABLE, "登录未启用：注册落点未声明")

    pool = _pool_or_503()
    private_key_pem, kid = _signer_or_503()
    try:
        user = await create_user(pool, body.login, body.password, org_id=org_id, display_name=body.display_name)
    except (InvalidLogin, InvalidPassword) as e:
        raise _map_input_error(e) from e
    except UserExistsError as e:
        raise AppError(409, CODE_LOGIN_TAKEN, "该登录名已存在，请直接登录") from e
    except AuthStoreUnavailable as e:
        logger.warning("注册失败：用户目录不可用", exc_info=True)
        raise AppError(503, CODE_STORE_UNAVAILABLE, "登录未启用：用户目录不可用") from e

    token = _issue(user.id, user.org_id, private_key_pem, kid)
    logger.info("用户注册成功 user=%s org=%s admin=%s", user.id, user.org_id, user.is_admin)
    response.headers["Cache-Control"] = "no-store"
    return TokenResponse(
        access_token=token,
        expires_in=settings.auth_token_ttl,
        tenant_id=user.org_id,
        user_id=user.id,
        is_admin=user.is_admin,
    )


@router.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest, response: Response) -> TokenResponse:
    """口令换令牌。对 ⇒ 200 + JWT；错 ⇒ 401，且**不区分**"账号不存在"与"口令不对"。"""
    settings = get_settings()
    pool = _pool_or_503()
    private_key_pem, kid = _signer_or_503()
    try:
        user = await verify_credentials(pool, body.login, body.password)
    except InvalidLogin as e:
        raise _map_input_error(e) from e
    except AuthStoreUnavailable as e:
        logger.warning("登录失败：用户目录不可用", exc_info=True)
        raise AppError(503, CODE_STORE_UNAVAILABLE, "登录未启用：用户目录不可用") from e

    if user is None:
        # 单一文案 + 单一 code：这条分支是 A3 的判据落点，改动它必须先过反证用例。
        logger.info("登录失败 login=%r（凭据不匹配，不区分成因）", _redact(body.login))
        raise AppError(401, CODE_CREDENTIALS_INVALID, CREDENTIALS_INVALID_MSG)

    token = _issue(user.id, user.org_id, private_key_pem, kid)
    try:
        await touch_last_login(pool, user.id)
    except AuthStoreUnavailable:
        pass  # 展示位失败不影响登录成立（这条不是安全边界，见 auth_users 的函数注释）
    logger.info("登录成功 user=%s org=%s", user.id, user.org_id)
    response.headers["Cache-Control"] = "no-store"
    return TokenResponse(
        access_token=token,
        expires_in=settings.auth_token_ttl,
        tenant_id=user.org_id,
        user_id=user.id,
        is_admin=user.is_admin,
    )


@router.get("/auth/me", response_model=MeResponse)
async def me() -> MeResponse:
    """回读**服务端已断言**的身份（A4 的判据面）。

    值只从 ContextVar 取（中间件验签后绑定的），不读请求体、不读查询参数 —— 这一格存在的
    意义就是"证明断言真的发生了"，所以它**不接受任何客户端可指定的身份输入**。

    为什么读 :func:`asserted_person_id` 而不是 ``asserted_user_id``：后者的值是中间件直接
    从 claim 绑的，而 ``verify_token`` 对缺 ``user_id`` 的**租户级令牌**会回落到 ``sub``
    （``identity.py:250``）—— 那不是一个“人”。拿它回给前端就等于是我们自己的端点把租户名
    说成了用户 id，而前端的登录态 UI 就靠这一格分辨“我登录了谁”。
    """
    user = asserted_person_id()
    tenant = asserted_tenant_id()
    if not user or not tenant:
        raise AppError(401, CODE_NOT_ASSERTED, "本次请求未携带可断言的身份")
    return MeResponse(tenant_id=tenant, user_id=user)


@router.post("/auth/logout")
async def logout(response: Response) -> dict[str, str]:
    """登出：服务端**无事可做**，令牌是无状态 RS256，没有会话表可清。

    这句必须如实读：本端点的作用是给前端一个明确的调用点与留痕，**已签发的令牌在 exp
    之前依然可用**。真正的撤销（jti 黑名单 / 短寿命 + refresh）属方案 §7 的 PR-3，
    现在把它当已具备就是骗人。
    """
    user = asserted_person_id()
    logger.info("登出请求 user=%r（服务端不撤销已签发令牌）", _redact(user or ""))
    response.headers["Cache-Control"] = "no-store"
    return {"status": "logged_out", "revoked": "false"}


def _redact(raw: str) -> str:
    """登录名进日志前收口：截断 + 只留字符集内的字符。

    登录名不是秘密（A3 的整个前提就是"存在性不保密"），但它是**用户输入**：原样进日志
    等于给换行/控制字符开了注入面（伪造日志行）。这里不做转义，只做"要么干净要么打码"。
    """
    text = (raw or "")[:64]
    try:
        return normalize_login(text)
    except InvalidLogin:
        return "***"
