# -*- coding: utf-8 -*-
"""用户目录（登录面的单一实现）：口令散列、注册、凭据校验、登录时间。

方案 docs/plans/plan-web-auth-user-minimal-2026-11-05.md 的 D-b/D-c/D-d/D-e/D-g 五条决策
落在此件。**它只管"这个人是谁 + 口令对不对"，不管令牌**——签发/验签仍是
:mod:`agent_runtime.identity` 那一条 RS256 通路（复用单一实现，不新造第二套身份轨），
本模块的产物交给宿主去 ``mint_token``。

分层（红线 1）：属 agent-runtime，只依赖 stdlib + ``argon2-cffi``（``[auth]`` extra）+
psycopg 鸭子类型池，**不 import 任何 applications/**。SQL 通路形态与
:mod:`agent_runtime.workspace_registry` 同构（``async`` 函数显式收 ``pool``，宿主在依赖里
取 ``get_pool()`` 传进来），因此也沿用它的两个 PG 错误码判据 ``_is_undefined_table`` /
``_is_undefined_column``（同包内复用，不复制一份判定逻辑）。

三条不可放宽的判据：

1. **``password_hash IS NULL`` ⇒ 一律拒绝**，绝不与空串比较（D-c）。写成 ``DEFAULT ''``
   就造出了「非空口令全不匹配、空串口令可过」的窗口，这里从列形状上就没有那个入口。
2. **登录名归一化**为 ``[a-z0-9._-]{3,32}`` 且首字符为字母数字，直接当 ``users.id`` 用（D-d）。
   字符集是 ``agent_core.guardrails.auth._PRINCIPAL_RE`` 的**真子集**（不含大写、不含
   ``:`` ``/`` 空格），所以归一化后的 id 可以安全拼进会话主体（方案 D-l）——这一条不是
   风格选择，是"不同账号不得落进同一个会话目录"的前置条件。
3. **「账号不存在」与「口令错」同形状、同耗时档**（A3）。前者不返回记录但照样消耗一次
   argon2 校验（``_burn``），否则响应时间会把"这个账号存不存在"泄漏给未鉴权的一端。

argon2 是**惰性导入**（与 ``identity.py`` 的 ``import jwt`` 同一手法）：没装 ``[auth]``
extra 时本模块仍可 import，失败点落在第一次真正散列时，由调用方转成 503 而不是 500，
也不是静默降级成"无口令可过"。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from agent_runtime.workspace_registry import _is_undefined_column, _is_undefined_table

__all__ = [
    "UserRecord",
    "UserExistsError",
    "AuthStoreUnavailable",
    "LOGIN_SHAPE_HINT",
    "PASSWORD_LENGTH_HINT",
    "normalize_login",
    "check_password_policy",
    "hash_password",
    "verify_password",
    "create_user",
    "verify_credentials",
    "touch_last_login",
]

# 入参形状的两条固定文案见下方 PASSWORD_MIN/PASSWORD_MAX 之后（文案要用到那两个量，定义必须后置）。
LOGIN_SHAPE_HINT = "登录名需为 3–32 位，以小写字母或数字开头，只可含 . _ - 与其后的小写字母数字"

# 归一化后的登录名形状（见模块 docstring 判据 2 的子集关系，勿放宽到大写/冒号）。
_LOGIN_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")

# 口令长度带。下限 8 是 OWASP 的最低建议值；上限 128 不是密码学需要，是防"超长串灌进
# argon2 把 CPU 打满"这类廉价 DoS（argon2 的成本与口令长度线性相关）。
PASSWORD_MIN = 8
PASSWORD_MAX = 128

# 两条入参文案是**要被外部引用的常量**，不是异常内部字符串：宿主直接拿它们填错误响应的
# ``msg``，而不写 ``str(exc)`` —— P8 不变量禁止对外响应体回显异常消息（它不区分“我自己写的
# 文案”与“库抛出的文本”，从语法上封死这一形）。文案里不含任何用户输入，所以可以直接给
# 用户看，前端也可以按 code 分支后自行覆盖。
PASSWORD_LENGTH_HINT = f"口令长度需在 {PASSWORD_MIN}–{PASSWORD_MAX} 字符之间"

# 与 runner 的 _MIGRATION_LOCK_KEY、scheduler 的 _SLOT_LOCK_KEY 都不冲突的独立 key。
_SEED_LOCK_KEY = 0xCAFE0016


class UserExistsError(ValueError):
    """登录名已被占用（users.id PK 冲突）。"""


class InvalidLogin(ValueError):
    """登录名不符合归一化形状。"""


class InvalidPassword(ValueError):
    """口令不符合长度带。"""


class AuthStoreUnavailable(RuntimeError):
    """用户目录不可用：库未配、迁移 016 未应用、或散列依赖缺失。

    这是**故意与"凭据不对"分开**的一类错误：前者必须是 503（服务没准备好），后者是 401。
    把两者混成一个 401 会让人以为口令错了，从而朝错误的方向排查。
    """


@dataclass(frozen=True)
class UserRecord:
    """口令校验通过后回给宿主的最小事实集（**不含 password_hash**，见类注释）。"""

    id: str
    org_id: str
    display_name: str
    is_admin: bool

    # 本类不加 password_hash 字段：散列一旦成为返回值的一部分，就可能顺着日志/响应体外流。
    # 校验在目录内部完成，宿主只拿"这个人是谁"。


# --- 散列（argon2 惰性） ----------------------------------------------------

_hasher = None


def _get_hasher():
    global _hasher
    if _hasher is not None:
        return _hasher
    try:
        from argon2 import PasswordHasher
    except ImportError as e:  # 未装 agent-runtime[auth]
        raise AuthStoreUnavailable("未安装 agent-runtime[auth]（argon2-cffi），口令面不可用") from e
    _hasher = PasswordHasher()
    return _hasher


_dummy_hash: str | None = None


def _verify_failures() -> tuple[type[BaseException], ...]:
    """argon2 的「口令不对 / 散列串坏了」失败形态（**不含**依赖缺失）。

    单独抽一个函数返回异常元组，是因为这几个类住在 ``argon2.exceptions`` 里，而本模块的
    argon2 是惰性导入（见模块 docstring 末段）：顶层写 ``from argon2.exceptions import ...``
    会把惰性导入这件事作废，没装 extra 的机器连 ``import agent_runtime.auth_users`` 都过不去。
    """
    from argon2.exceptions import Argon2Error, InvalidHashError, VerifyMismatchError

    # Argon2Error 是另两类的共同父类，也是该库**运行期**异常的根；捕它不触及 ImportError /
    # TypeError 之类的真故障，那些必须往外走（P0-4 盲捕获门禁盯的就是 ``except Exception``）。
    return (VerifyMismatchError, InvalidHashError, Argon2Error)


def _burn(password: str) -> None:
    """账号不存在时也消耗一次 argon2 校验，使两条分支落在同一耗时档（A3）。

    结果**不参与判决**（调用方随后一律返回 None），所以这里吞掉 argon2 的校验异常是
    语义正确的；但吞的是该类自己的异常清单（``_verify_failures``）而不是 ``except Exception``
    ——依赖缺失之类的问题照常往外抛，不让一次真故障伪装成"口令不对"。
    """
    global _dummy_hash
    if _dummy_hash is None:
        # 用固定串生成一次，之后所有 miss 分支复用同一枚（成本与真校验同量级）。
        _dummy_hash = hash_password("dummy-for-cost-equalization-0000")
    hasher = _get_hasher()  # 不在 try 内：缺依赖 ⇒ AuthStoreUnavailable，不是"烧掉时间"
    try:
        hasher.verify(_dummy_hash, password)
    except _verify_failures():
        return


def hash_password(password: str) -> str:
    """argon2id 散列（A1：库里存的必须是这一串的形态，不是明文）。"""
    return _get_hasher().hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """常量时间的口令校验。**NULL/空散列一律 False**（D-c），绝不把 NULL 喂进 argon2。"""
    if not password_hash:
        return False
    hasher = _get_hasher()  # 不在 try 内：依赖缺失必须是 AuthStoreUnavailable，不是"口令不对"
    try:
        return bool(hasher.verify(password_hash, password))
    except _verify_failures():
        return False


# --- 入参归一化 -------------------------------------------------------------

def normalize_login(raw: object) -> str:
    """把用户输入收成 ``users.id``：去首尾空白 → 小写 → 校形状。

    :raises InvalidLogin: 非字符串、空、超 32 字符，或含字符集外的任何字符
    """
    if not isinstance(raw, str):
        raise InvalidLogin(LOGIN_SHAPE_HINT)
    login = raw.strip().lower()
    if not _LOGIN_RE.match(login):
        raise InvalidLogin(LOGIN_SHAPE_HINT)
    return login


def check_password_policy(password: object) -> str:
    """口令长度带校验（本轮只有长度一条，没有复杂度规则：后者逼出的是一行便利贴）。"""
    if not isinstance(password, str):
        raise InvalidPassword(PASSWORD_LENGTH_HINT)
    if PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        return password
    raise InvalidPassword(PASSWORD_LENGTH_HINT)


# --- SQL 通路（async + 显式收 pool，与 workspace_registry 同形）-------------

def _require_pool(pool) -> None:
    if pool is None:
        raise AuthStoreUnavailable("用户目录需要 PostgreSQL（DATABASE_URL 未配置 ⇒ 内存模式无 users 表）")


async def create_user(
    pool,
    login: str,
    password: str,
    *,
    org_id: str,
    display_name: str = "",
    is_admin: bool | None = None,
) -> UserRecord:
    """注册一个口令账号（D-e/D-g）。

    三件事在**一个事务 + advisory_xact_lock** 里做完，不是三条各自autocommit 的语句：
    首账号提权（``is_admin=None`` ⇒ "表内零用户则 true"）是一个跨请求的判断，无锁时两个
    并发注册都会读到"还没有用户"，于是同秒产出两个管理员。锁 key 与迁移/scheduler 都不同。

    - 先 upsert ``organizations`` 那一行：``users.org_id`` 是 FK，不先补它会让注册当场炸
      （D-e 的"FK 不先补 organizations 行会当场炸注册"就是这条）；
    - ``INSERT ... ON CONFLICT DO NOTHING RETURNING id``：拿不到行即已被占用 → :class:`UserExistsError`；
    - 表/列不存在（013 或 016 未应用）→ :class:`AuthStoreUnavailable`，**不降级放行**：
      与 workspace_registry 的 ``register_workspace`` 不同，这里少一张表就等于少一整个安全
      边界，放行等于"没有用户目录也能建号"。
    """
    _require_pool(pool)
    name = normalize_login(login)
    check_password_policy(password)
    if not isinstance(org_id, str) or not org_id.strip():
        raise ValueError("org_id 必须为非空字符串（注册落哪个企业由部署声明，D-e）")
    pw_hash = hash_password(password)
    display = (display_name or "").strip()[:64]
    try:
        async with pool.connection() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(%s)", (_SEED_LOCK_KEY,))
                await conn.execute(
                    "INSERT INTO organizations (id) VALUES (%s) ON CONFLICT (id) DO NOTHING",
                    (org_id,),
                )
                admin = is_admin
                if admin is None:
                    cur = await conn.execute("SELECT 1 FROM users LIMIT 1")
                    admin = await cur.fetchone() is None
                cur = await conn.execute(
                    "INSERT INTO users (id, org_id, display_name, is_admin, password_hash) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "ON CONFLICT (id) DO NOTHING RETURNING id",
                    (name, org_id, display, bool(admin), pw_hash),
                )
                if await cur.fetchone() is None:
                    raise UserExistsError(f"登录名 {name!r} 已存在")
    except (UserExistsError, InvalidLogin, InvalidPassword, AuthStoreUnavailable):
        raise
    except Exception as e:
        if _is_undefined_table(e) or _is_undefined_column(e):
            raise AuthStoreUnavailable("用户目录表未就绪（migration 013/016 未应用）") from e
        raise
    return UserRecord(id=name, org_id=org_id, display_name=display, is_admin=bool(admin))


async def verify_credentials(pool, login: str, password: str) -> UserRecord | None:
    """口令校验。对 ⇒ 记录；错 ⇒ None。

    "账号不存在"与"口令不对"**返回同一个 None**（A3 的实现面，文案与状态码由宿主统一给）；
    ``password_hash`` 为 NULL 的账号走 ``verify_password`` 的 fail-closed 分支，同样返回 None。
    """
    _require_pool(pool)
    name = normalize_login(login)
    if not isinstance(password, str) or not password:
        # 空口令不进门：不去查库，也不给"这个账号存在吗"留时间信号。
        _burn(password or "")
        return None
    try:
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id, org_id, display_name, is_admin, password_hash FROM users WHERE id = %s",
                (name,),
            )
            row = await cur.fetchone()
    except Exception as e:
        if _is_undefined_table(e) or _is_undefined_column(e):
            raise AuthStoreUnavailable("用户目录表未就绪（migration 013/016 未应用）") from e
        raise
    if row is None:
        _burn(password)
        return None
    uid, org, display, admin, pw_hash = row
    if not verify_password(pw_hash, password):
        return None
    return UserRecord(id=uid, org_id=org, display_name=display or "", is_admin=bool(admin))


async def touch_last_login(pool, user_id: str) -> None:
    """记一次成功登录的时刻。失败不影响登录本身（这是展示位，不是安全边界）。"""
    _require_pool(pool)
    try:
        async with pool.connection() as conn:
            await conn.execute("UPDATE users SET last_login_at = now() WHERE id = %s", (user_id,))
    except Exception as e:
        if _is_undefined_column(e):
            return
        raise
