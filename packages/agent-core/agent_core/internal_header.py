"""内部签名租户头原语（ADR-0007 A3/A4，决策 1=A3）。

**零依赖纯 stdlib**，置于 agent-core 供 agent-runtime（网关签发/子服务）与 knowledge-service
（子服务校验）**共用同一实现**——避免签名格式在各服务重复实现而漂移（横切关注点单一实现原则）。

信任边界 B（网关 → 子服务）：网关用共享对称密钥对 ``X-Internal-Tenant`` 头签名，子服务校验后
才采信其中的租户断言。缺密钥/格式非法/签名不符/过期 → 抛 :class:`InternalHeaderError`（fail-closed）。

头格式：``v1.<b64url(json({"t":tenant,"u":user,"ts":epoch}))>.<hex hmac_sha256("v1.<b64url>")>``。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

__all__ = [
    "InternalHeaderError",
    "b64url_encode",
    "b64url_decode",
    "compute_header_sig",
    "sign_internal_header",
    "verify_internal_header",
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


def sign_internal_header(tenant: str, user: str | None = None, *, key: bytes, now: int | None = None) -> str:
    """签发内部头值 ``v1.<payload>.<sig>``。``key`` 必填（调用方加载，agent-core 不读环境）。"""
    if not key:
        raise InternalHeaderError("缺少内部 HMAC 密钥，无法签发")
    ts = now if now is not None else int(time.time())
    payload = b64url_encode(json.dumps({"t": tenant, "u": user, "ts": ts}, separators=(",", ":")).encode())
    body = f"v1.{payload}"
    return f"{body}.{compute_header_sig(key, body)}"


def verify_internal_header(value: str | None, *, key: bytes, max_age: int = 300) -> tuple[str, str | None] | None:
    """校验内部头值。

    - ``value`` 缺/空 → 返回 ``None``（头不存在，交调用方按软/硬模式处置）；
    - 存在但格式非法 / 签名不符 / 过期 / 缺租户 → :class:`InternalHeaderError`（存在即须可信）。
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
    ts = data.get("ts")
    if not isinstance(ts, int) or int(time.time()) - ts > max_age:
        raise InternalHeaderError("内部头过期/时间戳非法")
    tenant = data.get("t")
    if not isinstance(tenant, str) or not tenant.strip():
        raise InternalHeaderError("内部头缺 tenant")
    user = data.get("u")
    return tenant, user if isinstance(user, str) else None
