"""C1 上下文编解码器：JWT（默认）+ base64 适配器。

D1 默认值 = JWT（任务卡 §5）。两种方式通过配置切换：
- jwt：解析 JWT payload（mock 场景不验签，留 verify_signature 接口位；生产由网关验签）
- base64：base64(JSON) 解码（需平台侧签名防篡改，契约 §C1 选项 a）

不引入 pyjwt 重依赖：JWT 仅是 base64url 段拼接，手动解析 payload 即可。
验签接口位保留，生产注入密钥后启用。
"""

from __future__ import annotations

import base64
import json
from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)


def _b64url_decode(segment: str) -> bytes:
    """base64url 解码（补齐 padding）。"""
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def decode_jwt(token: str, *, verify_signature: bool = False, secret: str | None = None) -> dict[str, Any]:
    """解析 JWT 的 payload claim。

    结构：header.payload.signature（三段 base64url，点分隔）。
    - verify_signature=False（mock 默认）：仅解析 payload，不验签。
    - verify_signature=True：需 secret，用 HS256 验签（生产由网关/中间件启用）。

    raise ValueError：结构非法或 payload 非 JSON。
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError(f"JWT 结构非法：期望 3 段，实际 {len(parts)} 段")
    try:
        payload_bytes = _b64url_decode(parts[1])
        payload = json.loads(payload_bytes)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"JWT payload 解析失败：{exc}") from exc

    if verify_signature:
        if secret is None:
            raise ValueError("verify_signature=True 但 secret 未提供")
        import hashlib
        import hmac

        signing_input = f"{parts[0]}.{parts[1]}".encode()
        expected = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
        actual = _b64url_decode(parts[2])
        if not hmac.compare_digest(expected, actual):
            raise ValueError("JWT 签名无效")

    if not isinstance(payload, dict):
        raise ValueError(f"JWT payload 必须是 JSON object，实际 {type(payload).__name__}")
    return payload


def decode_base64(token: str) -> dict[str, Any]:
    """base64(JSON) 解码（适配器选项 a，需平台侧签名防篡改）。

    raise ValueError：解码失败或非 JSON object。
    """
    try:
        raw = base64.b64decode(token)
        payload = json.loads(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"base64 上下文解析失败：{exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"上下文必须是 JSON object，实际 {type(payload).__name__}")
    return payload


def encode_base64(payload: dict[str, Any]) -> str:
    """base64(JSON) 编码（适配器选项 a，供 demo/测试生成头）。"""
    return base64.b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode()


def encode_jwt(payload: dict[str, Any], *, secret: str | None = None) -> str:
    """JWT 编码（无签名 mock 版，供 demo/测试生成头）。

    生产由平台网关签发（带 HS256 签名）；本函数生成无签名 JWT（signature 段为空），
    仅供 mock/测试使用。verify_signature=False 的解码器可解析。
    """
    header = {"alg": "none", "typ": "JWT"}
    header_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=").decode()
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode()).rstrip(b"=").decode()

    if secret is not None:
        import hashlib
        import hmac

        signing_input = f"{header_b64}.{payload_b64}".encode()
        sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
        sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    else:
        sig_b64 = ""

    return f"{header_b64}.{payload_b64}.{sig_b64}"
