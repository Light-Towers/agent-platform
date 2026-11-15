"""认证与会话策略。

安全设计（沿用 deepagents 已验证的结论）：鉴权启用时忽略客户端传入的
thread_id，改为按**服务端断言的主体**派生，防止会话劫持；thread_id 仅在开发
模式（未启用鉴权）下信任客户端。

B7b-4（拆 CodeQL ``py/weak-sensitive-data-hashing`` 链①）：会话身份不再从调用方
凭据派生。旧内核函数 ``derive_thread_id``（形参即 ``api_key``）把「谁持有这把密钥」当身份熵源，
而 ``API_KEY`` 每部署一把 ⇒ 它今天本就等价于「一个部署一个桶」；换成断言租户后
桶数不变（见 ``resolve_thread_id`` docstring 的等价性说明），但凭据彻底退出派生。
派生实现仍收敛内核（DUP-1）：``agent_core.guardrails.auth.resolve_thread_identity``。

入站凭据**只有一条**（本部署拍板「只留用户名/密码登录」）：``Authorization: Bearer
<RS256 JWT>`` 由 ``IdentityMiddleware`` 验签并断言到人，本件只读断言结果。静态
``X-API-Key`` 通道已退役——本件不再接收也不比对该头。

⚠ ``settings.api_key`` **保留**，但语义已从「要比对的静态密钥」收窄为「鉴权启用开关」：
它同时是 ``resolve_thread_id`` 是否信任客户端 thread_id 的判据，删掉该字段会让会话
退化为客户端可指定（会话劫持面），故不能用「删 env」的方式退役静态通道。
``settings.api_key`` 未配即不校验的 dev 旁路**照旧不动**（那是 U1，本件不代答）。
"""

from typing import Callable

from agent_core.guardrails.auth import DEV_THREAD_ID, resolve_thread_identity
from agent_core.guardrails.errors import AppError
from agent_runtime.authorization import effective_role, has_feature
from agent_runtime.workspace_registry import (
    asserted_person_id,
    asserted_role,
    asserted_tenant_id,
    asserted_user_id,
    server_tenant_id,
)
from fastapi import HTTPException

from agent_server.config import get_settings

# 对外稳定错误码（前端按 code 分支；与 auth_router 的 CODE_* 同族命名）。
# 值与方案 §3 D10 / §4:111 对齐；feature 码只进 details，不进 msg（不把能力清单外泄）。
CODE_FEATURE_FORBIDDEN = "FORBIDDEN_FEATURE"

# D-l 会话主体的用户段分隔。选 ``--user-`` 而不是 ``/`` ``:`` ``#``：它们都不在
# ``safe_filename`` 白名单内（会被有损改写成 ``_``，制造不同账号落同一目录的碰撞面），
# 而 ``-`` 在集合内；双连字符降低与租户名/登录名自身内容的歧义（登录名允许 ``-``）。
_USER_SEGMENT = "--user-"

# ``_PRINCIPAL_RE`` 的总长上限（``^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`` ⇒ 主体 ≤ 64）。
# 在此显式列写而不是“靠内核正则报错兼容”：超长的成因是“两段各自合法、拼起来超长”，
# 而 ``resolve_thread_identity`` 的文案是「字符集非法（会被有损改写）」，会误导排查方向。
_PRINCIPAL_MAX = 64


def verify_api_key() -> None:
    """入口鉴权闸门：**只接受登录令牌已断言到人的请求**，静态 X-API-Key 通道已退役。

    本件不再声明 ``X-API-Key`` 头参数，故该头既不参与鉴权、也不出现在 OpenAPI 里；
    带上它也一律按「无凭据」处理。放行只有两种成因：

    - ``asserted_person_id()`` 非 ``None``：``IdentityMiddleware`` 已验签 RS256 登录令牌
      并断言到人 —— 本部署唯一在用的入站通道；
    - ``settings.api_key`` 为空：纯开发模式旁路（U1，本件不代答）。生产现网该键非空。

    返回值恒为 ``None``：调用方一律写 ``_auth=Depends(...)`` 不取返回值（P12 不变量
    盯的就是这个——凭据值根本不再进入依赖树，从源头消掉「原文当审计主体」那条链）。

    ⚠ 判据必须是 :func:`asserted_person_id`（或 ``asserted_user_id``），**不得**换成
    ``asserted_tenant_id()``：SINGLE_TENANT 部署下中间件给**每个**请求都绑租户
    （``identity_middleware.py:190`` 的 ``_run(single, None, ...)`` 实取），拿它当「已登录」
    等于把整条闸门旁路 = fail-open。这一句不是推测，是本轮读代码抬出来的，改判据前先复取。

    ⚠ ``settings.api_key`` 在这里只当**开关**读（空=dev 旁路），其值绝不参与任何比对：
    它仍被 ``resolve_thread_id`` 用作「是否忽略客户端 thread_id」的判据，不能删字段。
    """
    if asserted_person_id() is not None:
        return None  # JWT 登录令牌已验签并断言到人
    settings = get_settings()
    if not settings.api_key:
        return None  # 开发模式：未启用鉴权（U1）
    raise HTTPException(status_code=401, detail="需要登录令牌")


def require_feature(code: str) -> Callable[[], None]:
    """feature 守卫（1b，D4/D10；第三轮升级点 2 的单一实现——**不是**逐端点 inline if）。

    端点写 ``_feature=Depends(require_feature("sql.train"))`` 挂上；**漏挂 = 无守卫**
    （守卫不做存在性扫描，漏接面由 R3/R10 逐端点反证承担）。判定单一在
    ``agent_runtime.authorization.has_feature``（D3：角色→能力只有一张常量表）：

    - role 取服务端断言的**原始 claim 值**（``asserted_role``，中间件已随令牌绑定）；
      值域收敛（未知/缺失码 → viewer 兜底 + D9 可聚合计数）单一在 ``effective_role``
      ——本件不解释角色词汇表，也不写第二份兜底口径。
    - 未断言到人的调用方（observe 档无令牌 / dev 旁路）⇒ ``asserted_role()`` 为
      ``None`` ⇒ viewer 兜底（P8 已拍 (a)：与 D9 同一条「无断言→最小权限」规则）。
      其能力面由 §4 矩阵决定：``chat.run``/``session.history`` 放行，写面 403（R10）。
    - 与 :func:`verify_api_key` 同族并存：401（凭据无效）先于 403（角色不够）——
      FastAPI 按参数声明顺序执行依赖，调用方把 ``_auth`` 放在 ``_feature`` 之前。

    msg 是固定文案不含内部细节；feature 码只进 ``details``（D10：不进 ``msg``，
    不把能力清单回显给未授权调用方），由统一错误信封渲染。
    """
    def _guard() -> None:
        role = effective_role(
            asserted_role(),
            tenant=asserted_tenant_id() or "",
            user=asserted_user_id() or "",
        )
        if not has_feature(role, code):
            raise AppError(
                403,
                CODE_FEATURE_FORBIDDEN,
                "当前角色无权执行该操作",
                details={"feature": code},
            )

    # 具名化让 FastAPI 依赖树/调试日志可见（同名 dependency 会缓存——每个 feature 码独立函数名，互不串）。
    _guard.__name__ = f"require_{code.replace('.', '_')}"
    _guard.__qualname__ = _guard.__name__
    return _guard


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
            # 无“人”可断言（网关租户级令牌 / observe 档无凭据）⇒ 逐字保持旧主体。
            # 这一格是 A6 的后半判据：改成任何前缀/后缀都等于把存量会话线弄丢。
            return resolve_thread_identity(tenant)
        return resolve_thread_identity(_compose_principal(tenant, person))
    return client_thread_id or DEV_THREAD_ID
