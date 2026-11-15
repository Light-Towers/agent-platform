"""内部签名租户头原语（ADR-0007 A3/A4，决策 1=A3）。

**零依赖纯 stdlib**，置于 agent-core 供 agent-runtime（网关签发/子服务）与 knowledge-service
（子服务校验）**共用同一实现**——避免签名格式在各服务重复实现而漂移（横切关注点单一实现原则）。

信任边界 B（网关 → 子服务）：网关用共享对称密钥对 ``X-Internal-Tenant`` 头签名，子服务校验后
才采信其中的租户断言。缺密钥/格式非法/签名不符/过期 → 抛 :class:`InternalHeaderError`（fail-closed）。

头格式：``v1.<b64url(json({"t":tenant,"u":user,"ts":epoch[,"r":role]}))>.<hex hmac_sha256("v1.<b64url>")>``。
``r`` 是 1c/D11 的**可选承载键**：只在签发方显式给 role 时写入，旧验签方按 ``.get()`` 取值
⇒ 加键是向后兼容的扩展方向，滚动升级窗口里「新签发方 × 旧验签方」安全（F17 / ADR-0015 §4.2）。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

__all__ = [
    "InternalHeaderError",
    "b64url_encode",
    "b64url_decode",
    "compute_header_sig",
    "load_hmac_key",
    "sign_internal_header",
    "verify_internal_header",
    "verify_internal_header_with_role",
]


class InternalHeaderError(Exception):
    """内部签名头校验失败（缺密钥 / 格式非法 / 签名不符 / 过期 / 缺租户）。"""


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def compute_header_sig(key: bytes, body: str) -> str:
    """对 ``body``（``v1.<payload>`` 段）计算 HMAC-SHA256 十六进制签名。"""
    return hmac.new(key, body.encode(), hashlib.sha256).hexdigest()


def load_hmac_key(path: str | None = None) -> bytes | None:
    """加载内部签名头共享对称密钥（网关 + 子服务双方持有）。

    从 ``INTERNAL_HMAC_KEY_FILE`` 指向的文件读取（密钥走挂载/密钥库，绝不进仓库）。缺 → None。
    """
    path = path or os.getenv("INTERNAL_HMAC_KEY_FILE", "")
    if not path or not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read().strip()


def sign_internal_header(
    tenant: str,
    user: str | None = None,
    *,
    key: bytes,
    now: int | None = None,
    role: str | None = None,
) -> str:
    """签发内部头值 ``v1.<payload>.<sig>``。``key`` 必填（调用方加载，agent-core 不读环境）。

    ``role`` 为 1c/D11 的可选承载位：仅在非 None 时写 payload 的 ``r`` 键。**加键而非改
    已有键语义**，旧验签方用 ``.get("t")/("u")`` 取值的形状不受影响（F17）。
    """
    if not key:
        raise InternalHeaderError("缺少内部 HMAC 密钥，无法签发")
    ts = now if now is not None else int(time.time())
    data: dict[str, object] = {"t": tenant, "u": user, "ts": ts}
    if role is not None:
        data["r"] = role
    payload = b64url_encode(json.dumps(data, separators=(",", ":")).encode())
    body = f"v1.{payload}"
    return f"{body}.{compute_header_sig(key, body)}"


def _decode_payload(value: str | None, *, key: bytes, max_age: int = 300) -> dict | None:
    """验签 + 解析 payload，返回完整 dict；缺头 → None，其余失败 → InternalHeaderError。

    单一实现供 :func:`verify_internal_header`（二元组，向后兼容）与
    :func:`verify_internal_header_with_role`（三元组，1c 承载）共用，避免验签逻辑两份。
    """
    if not value:
        return None
    if not key:
        raise InternalHeaderError("收到内部头但未配置 HMAC 密钥，无法校验")
    parts = value.split(".")
    if len(parts) != 3 or parts[0] != "v1":
        raise InternalHeaderError("内部头格式非法")
    _, payload, sig = parts
    if not hmac.compare_digest(compute_header_sig(key, f"v1.{payload}"), sig):
        raise InternalHeaderError("内部头签名不符（疑似伪造）")
    try:
        data = json.loads(b64url_decode(payload))
    except (ValueError, UnicodeDecodeError) as e:
        raise InternalHeaderError("内部头 payload 解析失败") from e
    if not isinstance(data, dict):
        raise InternalHeaderError("内部头 payload 非法")
    ts = data.get("ts")
    if not isinstance(ts, int) or int(time.time()) - ts > max_age:
        raise InternalHeaderError("内部头过期/时间戳非法")
    tenant = data.get("t")
    if not isinstance(tenant, str) or not tenant.strip():
        raise InternalHeaderError("内部头缺 tenant")
    return data


def _tenant_user(data: dict) -> tuple[str, str | None]:
    user = data.get("u")
    return data["t"], user if isinstance(user, str) else None


def verify_internal_header(
    value: str | None, *, key: bytes, max_age: int = 300
) -> tuple[str, str | None] | None:
    """校验内部头值（**保持二元组返回**，KS fork 与存量验签方不受影响）。

    - ``value`` 缺/空 → ``None``（头不存在，交调用方按软/硬模式处置）；
    - 存在但格式非法 / 签名不符 / 过期 / 缺租户 → :class:`InternalHeaderError`。
    - payload 里新增的 ``r`` 键在此**被忽略**（带而不用）；需要 role 的调用方用
      :func:`verify_internal_header_with_role`。
    """
    data = _decode_payload(value, key=key, max_age=max_age)
    return None if data is None else _tenant_user(data)


def verify_internal_header_with_role(
    value: str | None, *, key: bytes, max_age: int = 300
) -> tuple[str, str | None, str | None] | None:
    """1c/D11：返回 ``(tenant, user, role)``；无 ``r`` 键（旧签发方）⇒ ``role=None``。

    消费侧必须按「无 role ⇒ 最小权限」处置（``effective_role`` / ``has_feature``），
    **不得把 None 当 admin**。独立函数而非改 :func:`verify_internal_header` 的返回形状，
    是为了让滚动升级窗口里旧验签方继续用二元组解包（F17）。
    """
    data = _decode_payload(value, key=key, max_age=max_age)
    if data is None:
        return None
    tenant, user = _tenant_user(data)
    role = data.get("r")
    return tenant, user, role if isinstance(role, str) and role.strip() else None
