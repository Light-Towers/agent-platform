"""认证与会话策略。

安全设计（沿用 deepagents 已验证的结论）：API_KEY 启用时忽略客户端传入的
thread_id，改为按**服务端断言的主体**派生，防止会话劫持；thread_id 仅在开发
模式（未启用 API_KEY）下信任客户端。

B7b-4（拆 CodeQL ``py/weak-sensitive-data-hashing`` 链①）：会话身份不再从调用方
凭据派生。旧内核函数 ``derive_thread_id``（形参即 ``api_key``）把「谁持有这把密钥」当身份熵源，
而 ``API_KEY`` 每部署一把 ⇒ 它今天本就等价于「一个部署一个桶」；换成断言租户后
桶数不变（见 ``resolve_thread_id`` docstring 的等价性说明），但凭据彻底退出派生。
派生实现仍收敛内核（DUP-1）：``agent_core.guardrails.auth.resolve_thread_identity``。

登录面接入后本件是**两条入口凭据的汇合点**（方案 D-i：并存，不替换）：
``Authorization: Bearer <RS256 JWT>`` 由 ``IdentityMiddleware`` 验签后绑定断言，本件
只读断言结果；``X-API-Key`` 仍是机器对机器调用的通路（ADR-0008 U2 未答，删它等于替
它答题）。``settings.api_key`` 未配即不校验的旁路**照旧不动**（那是 U1，本件不代答）。
"""

import secrets

from agent_core.guardrails.auth import DEV_THREAD_ID, resolve_thread_identity
from agent_runtime.workspace_registry import asserted_person_id, server_tenant_id
from fastapi import Header, HTTPException

from agent_server.config import get_settings

# D-l 会话主体的用户段分隔。选 ``--user-`` 而不是 ``/`` ``:`` ``#``：它们都不在
# ``safe_filename`` 白名单内（会被有损改写成 ``_``，制造不同账号落同一目录的碰撞面），
# 而 ``-`` 在集合内；双连字符降低与租户名/登录名自身内容的歧义（登录名允许 ``-``）。
_USER_SEGMENT = "--user-"

# ``_PRINCIPAL_RE`` 的总长上限（``^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`` ⇒ 主体 ≤ 64）。
# 在此显式列写而不是“靠内核正则报错兼容”：超长的成因是“两段各自合法、拼起来超长”，
# 而 ``resolve_thread_identity`` 的文案是「字符集非法（会被有损改写）」，会误导排查方向。
_PRINCIPAL_MAX = 64


def verify_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> str | None:
    """入口鉴权闸门：已断言到人 ⇒ 直接放行；否则回落既有静态 key 比对。

    返回 ``None`` 现在有两种成因（开发模式未校 / 已由令牌鉴权），两者共同含义是
    「已放行且无凭据值可回」；调用方一律写成 ``_auth=Depends(...)`` 不取返回值
    （P12 不变量盯的就是这个，现在两种 ``None`` 不会给它新缺口）。

    ⚠ 判据必须是 :func:`asserted_person_id`（或 ``asserted_user_id``），**不得**换成
    ``asserted_tenant_id()``：SINGLE_TENANT 部署下中间件给**每个**请求都绑租户
    （``identity_middleware.py:190`` 的 ``_run(single, None, ...)`` 实取），那等于把静态 key
    整条旁路 = fail-open。这一句不是推测，是本轮读代码抬出来的，改动本判据前先复取它。
    """
    if asserted_person_id() is not None:
        return None  # 已由中间件验签并断言到人（D-i 并存）
    settings = get_settings()
    if not settings.api_key:
        return None  # 开发模式：不校验
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="API Key 无效")
    return x_api_key


def _compose_principal(tenant: str, person: str) -> str:
    """拼出登录态的会话主体 ``<tenant>--user-<person>``，超长即报错（不静默退化）。

    为什么这里是 **raise** 而不是“那就只按租户分桶”：能走到这一层的两段值已经过了
    :func:`asserted_person_id` 的字符集与同名校验 ⇒ 超长只可能是部署配置的租户 slug 过长，
    而“默默退回租户桶”就是把两个账号塞回同一个会话目录 —— 那正是 D-l 要消除的产品级错误，
    不能拿它当降级方案。宁可首个请求就红，不可静默共用目录（与内核同一条纪律）。
    """
    principal = f"{tenant}{_USER_SEGMENT}{person}"
    if len(principal) > _PRINCIPAL_MAX:
        raise ValueError(
            f"会话主体超长（{len(principal)} > {_PRINCIPAL_MAX}）：租户 {tenant!r} 与用户 {person!r} "
            "各自合法但拼不成 filename-safe 主体；请缩短 DEFAULT_TENANT_ID/SIGNUP_ORG_ID 的 slug"
        )
    return principal


def resolve_thread_id(client_thread_id: str | None) -> str:
    """解析本次请求应使用的 thread_id（**签名里没有凭据位**，凭据在类型层面进不来）。

    :param client_thread_id: 客户端传入的会话标识，仅在开发模式被信任
    :return: 认证启用且断言到人 → ``tenant-<t>--user-<u>``；认证启用但无人 →
        ``tenant-<t>``（与 D-l 前**逐字相同**）；开发模式 → 客户端值或 ``DEV_THREAD_ID``
    """
    settings = get_settings()
    if settings.api_key:
        # 认证启用：忽略客户端 thread_id（防劫持），主体取服务端已断言的租户
        # （ContextVar 优先，其次部署级 default —— 与 import/sql_router、capabilities 同写法）
        tenant = server_tenant_id(settings.default_tenant_id)
        person = asserted_person_id()
        if person is None:
            # 无“人”可断言（静态 key / 网关租户级令牌 / observe 档无凭据）⇒ 逐字保持旧主体。
            # 这一格是 A6 的后半判据：改成任何前缀/后缀都等于把存量会话线弄丢。
            return resolve_thread_identity(tenant)
        return resolve_thread_identity(_compose_principal(tenant, person))
    return client_thread_id or DEV_THREAD_ID
