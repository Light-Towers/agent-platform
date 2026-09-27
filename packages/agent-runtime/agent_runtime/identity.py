"""租户身份断言（ADR-0007 A3/A4）：RS256 JWT 验签/签发 + 内部 HMAC 签名头 + 上下文绑定 + 启动守卫。

设计：
- **纯逻辑 + os.environ 读取**，框架无关；middleware（FastAPI）在各 app 里薄封装调用本模块。
- ``jwt`` 在函数内**惰性 import**：未装 ``agent-runtime[identity]`` 可选 extra 时本模块仍可导入，
  HMAC / 上下文 / 启动守卫部分可用（PyJWT[crypto] 只在真正签/验 JWT 时才需要，红线 1：不进 agent-core）。
- 租户绑定复用 :mod:`agent_runtime.workspace_registry` 的 ``bind_tenant_context`` / ``server_tenant_id``
  （同一 ContextVar，避免 server_tenant_id 读不到绑定的裂脑）。

信任链（ADR-0007 §3）::

    外部客户端 --(RS256 JWT)--> [网关: verify_token → bind_tenant_context]   # issuer 随网关
    网关 --(X-Internal-Tenant + HMAC)--> [子服务: verify_internal_header → bind_tenant_context]
    子服务 → server_tenant_id() → store 谓词 WHERE tenant_id = %s
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

from agent_core.internal_header import InternalHeaderError
from agent_core.internal_header import sign_internal_header as _core_sign
from agent_core.internal_header import verify_internal_header as _core_verify

from agent_runtime.workspace_registry import (
    _TENANT_UNSET,
    bind_tenant_context,
    bind_user_context,
    server_tenant_id,
)

__all__ = [
    "IdentityError",
    "TokenClaims",
    "env_bool",
    "load_public_keys",
    "load_private_key",
    "load_hmac_key",
    "mint_token",
    "verify_token",
    "sign_internal_header",
    "verify_internal_header",
    "apply_tenant_context",
    "resolve_startup_tenant_mode",
    "require_identity_startup_guard",
    "extract_bearer",
    "get_header_tenant",
    "resolve_tenant_context",
]


class IdentityError(Exception):
    """身份令牌/签名头校验失败（验签、过期、缺 claim、HMAC 不符等）。"""


@dataclass(frozen=True)
class TokenClaims:
    tenant_id: str
    user_id: str | None = None
    jti: str | None = None
    exp: int | None = None
    iat: int | None = None


# --- 环境变量辅助 -----------------------------------------------------------

def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def extract_bearer(authorization: str | None) -> str | None:
    """从 Authorization 头取 Bearer token（大小写不敏感）；非 Bearer → None。"""
    if authorization and authorization.lower().startswith("bearer "):
        tok = authorization[7:].strip()
        return tok or None
    return None


def get_header_tenant(headers, *, header_name: str = "X-Internal-Tenant", hmac_key: bytes | None = None):
    """校验内部签名头，返回 (tenant, user) 或 None（缺头）。供子服务软/硬模式复用。

    无该头 → None（交调用方按软/硬模式处置）；有头但伪造/过期 → IdentityError。
    """
    value = headers.get(header_name) if headers is not None else None
    if not value:
        return None
    return verify_internal_header(value, key=hmac_key if hmac_key is not None else load_hmac_key())


def resolve_tenant_context(provided: str | None = None, *, default: str | None = None) -> str:
    """统一租户解析优先级（ADR-0007）：ContextVar 断言 > 入站 provided > default。

    default=None 且 ContextVar 未绑定 → 交由 server_tenant_id fail-fast（不静默兜底）。
    """
    bound = _tenant_ctx_value()
    if bound is not None:
        return bound
    p = (provided or "").strip()
    if p:
        return p
    return server_tenant_id(default if default is not None else _TENANT_UNSET)


def _tenant_ctx_value() -> str | None:
    """读服务端租户 ContextVar：绑定过则返回值，否则 None（不触发 fail-fast）。"""
    from agent_runtime import workspace_registry as _wr

    v = _wr._tenant_id_ctx.get()
    return None if v is _TENANT_UNSET else v


# 直接读 ContextVar（避免 default 哨兵干扰）：绑定过则返回值，否则 None。
def _read_tenant_ctx() -> str | None:
    return _tenant_ctx_value()


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# --- 密钥加载（文件走密钥库/挂载，绝不进仓库）--------------------------------

def load_public_keys(path: str | None = None) -> dict[str, str]:
    """从 JSON 文件加载 ``{kid: PEM 公钥}``（多把并存以支持轮转）。缺文件 → 空 dict。"""
    path = path or os.getenv("TENANT_JWT_PUBLIC_KEYS_FILE", "")
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return {str(k): str(v) for k, v in json.load(f).items()}


def load_private_key(path: str | None = None) -> str | None:
    """加载签发方私钥 PEM（仅网关/issuer 持有）。"""
    path = path or os.getenv("TENANT_JWT_PRIVATE_KEY_FILE", "")
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_hmac_key(path: str | None = None) -> bytes | None:
    """加载内部签名头共享对称密钥（网关 + 子服务双方持有）。"""
    path = path or os.getenv("INTERNAL_HMAC_KEY_FILE", "")
    if not path or not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read().strip()


# --- RS256 JWT 签发 / 验签 --------------------------------------------------

def mint_token(
    tenant_id: str,
    *,
    user_id: str | None = None,
    private_key_pem: str,
    kid: str,
    issuer: str | None = None,
    audience: str | None = None,
    ttl: int = 900,
    jti: str | None = None,
) -> str:
    """签发 RS256 JWT（网关/issuer 用；持私钥）。claims: tenant_id/user_id/exp/iat/sub(+jti)。"""
    import jwt  # 惰性：仅签发/验签路径需要 PyJWT[crypto]

    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": user_id or tenant_id,
        "tenant_id": tenant_id,
        "iat": now,
        "exp": now + ttl,
        "iss": issuer or os.getenv("TENANT_JWT_ISSUER", "agent-gateway"),
        "aud": audience or os.getenv("TENANT_JWT_AUDIENCE", "agent-platform"),
    }
    if user_id:
        payload["user_id"] = user_id
    if jti:
        payload["jti"] = jti
    return jwt.encode(payload, private_key_pem, algorithm="RS256", headers={"kid": kid})


def verify_token(
    token: str,
    *,
    public_keys: dict[str, str] | None = None,
    issuer: str | None = None,
    audience: str | None = None,
    max_ttl: int | None = None,
    leeway: int | None = None,
) -> TokenClaims:
    """验签 RS256 JWT 并校验 claim。任何不符 → :class:`IdentityError`（fail-closed）。

    - 按 header ``kid`` 选公钥（无 kid 则逐一尝试）；
    - 强制 ``exp``/``iat``/``sub``；leeway 容忍时钟偏移；
    - ``exp - iat`` 不得超过 ``max_ttl``（防误签超长令牌）；
    - 必须含非空 ``tenant_id`` claim（否则视为无效身份）。
    """
    import jwt

    keys = public_keys if public_keys is not None else load_public_keys()
    if not keys:
        raise IdentityError("未配置验签公钥（TENANT_JWT_PUBLIC_KEYS_FILE）")
    issuer = issuer or os.getenv("TENANT_JWT_ISSUER", "agent-gateway")
    audience = audience or os.getenv("TENANT_JWT_AUDIENCE", "agent-platform")
    max_ttl = max_ttl if max_ttl is not None else _int_env("TENANT_JWT_MAX_TTL_S", 3600)
    leeway = leeway if leeway is not None else _int_env("TENANT_JWT_CLOCK_SKEW", 60)

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as e:  # noqa: BLE001 - 转为域内错误，不外泄库细节
        raise IdentityError(f"令牌格式非法: {e}") from e

    kid = header.get("kid")
    # 本方案签发的令牌必带 kid；无 kid 或公钥已下线（轮转后）→ 直接拒（不逐一试密钥）。
    if not kid or kid not in keys:
        raise IdentityError(f"令牌 kid 缺失或无匹配公钥: {kid!r}")
    decode_keys: Any = keys[kid]
    try:
        payload = jwt.decode(
            token,
            decode_keys,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
            leeway=leeway,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError as e:
        raise IdentityError(f"令牌验签/校验失败: {e}") from e

    iat = payload.get("iat")
    exp = payload.get("exp")
    if isinstance(iat, int) and isinstance(exp, int) and (exp - iat) > max_ttl:
        raise IdentityError(f"令牌 TTL {exp - iat}s 超上限 {max_ttl}s")
    tenant = payload.get("tenant_id")
    if not isinstance(tenant, str) or not tenant.strip():
        raise IdentityError("令牌缺少 tenant_id claim")
    return TokenClaims(
        tenant_id=tenant,
        user_id=payload.get("user_id") or payload.get("sub"),
        jti=payload.get("jti"),
        exp=exp if isinstance(exp, int) else None,
        iat=iat if isinstance(iat, int) else None,
    )


# --- 内部签名头（信任边界 B：网关 → 子服务）--------------------------------
# 签名/验签原语单一实现于 agent_core.internal_header（零依赖 stdlib，knowledge-service 亦复用）；
# 本层仅负责密钥加载 + max_age 环境默认 + 将 InternalHeaderError 归一为 IdentityError。

def sign_internal_header(tenant_id: str, user_id: str | None = None, *, key: bytes | None = None) -> str:
    """签发 ``v1.<payload>.<sig>`` 内部头。key 缺则从 INTERNAL_HMAC_KEY 加载。"""
    key = key if key is not None else load_hmac_key()
    if not key:
        raise IdentityError("未配置 INTERNAL_HMAC_KEY（内部签名头无法签发）")
    return _core_sign(tenant_id, user_id, key=key)


def verify_internal_header(
    value: str | None,
    *,
    key: bytes | None = None,
    max_age: int | None = None,
) -> tuple[str, str | None] | None:
    """校验内部签名头（委托 agent-core 原语）。缺头→None；伪造/过期/格式非法→IdentityError。"""
    if not value:
        return None
    key = key if key is not None else load_hmac_key()
    if not key:
        raise IdentityError("收到内部头但未配置 INTERNAL_HMAC_KEY，无法校验")
    if max_age is None:
        max_age = _int_env("INTERNAL_HEADER_MAX_AGE_S", 300)
    try:
        return _core_verify(value, key=key, max_age=max_age)
    except InternalHeaderError as e:
        raise IdentityError(str(e)) from e


def apply_tenant_context(tenant_id: str, user_id: str | None = None):
    """绑定已断言的 tenant/user 到请求上下文；返回 (tenant_token, user_token) 供复位。"""
    return bind_tenant_context(tenant_id), bind_user_context(user_id)


# --- 启动守卫（封死 auth.py "未配 key 即不校验" 多租户裸奔，ADR-0007 §4.1）--

def resolve_startup_tenant_mode() -> tuple[str, str | None]:
    """返回 ``("jwt", None)`` | ``("single", tenant)`` | ``("insecure", None)``。

    优先级：配置了验签公钥 → jwt；否则显式 ``SINGLE_TENANT`` → single；否则 insecure。
    """
    if load_public_keys():
        return "jwt", None
    single = os.getenv("SINGLE_TENANT", "").strip()
    if single:
        return "single", single
    return "insecure", None


def require_identity_startup_guard(component: str = "service") -> str:
    """生产 fail-fast：既无验签公钥又未声明 ``SINGLE_TENANT`` 且 ``DEPLOY_ENFORCE_IDENTITY=true``
    → 抛错拒绝启动。未开启强制时（insecure）仅告警，返回模式供调用方决定是否绑定单租户上下文。
    """
    mode, _tenant = resolve_startup_tenant_mode()
    if mode != "insecure":
        return mode
    if env_bool("DEPLOY_ENFORCE_IDENTITY", False):
        raise RuntimeError(
            f"[identity] {component} 启动被拒：多租户生产须配置 RS256 验签公钥或显式声明 "
            f"SINGLE_TENANT=<tenant>（DEPLOY_ENFORCE_IDENTITY=true 已开启 fail-fast）。"
            f"见 docs/adr/0007-server-asserted-tenant-identity.md §4.1"
        )
    return mode
