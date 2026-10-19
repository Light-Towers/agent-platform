"""C1 上下文编解码器：JWT（默认）+ base64 适配器。

D1 默认值 = JWT（任务卡 §5）。两种方式通过配置切换：
- jwt：解析 JWT payload（mock 场景不验签，留 verify_signature 接口位；生产由网关验签）
- base64：base64(JSON) 解码（需平台侧签名防篡改，契约 §C1 选项 a）

2026-10-19 起 JWT 段走 **PyJWT 标准库**（issue #85，方案
``docs/plans/plan-execution-context-pyjwt-2026-10-19.md``）：此前是手写三段
base64url + 手写 HS256 HMAC。迁移原则 = **wire 逐位兼容 + 错误文案逐条保持**
（中间件把本模块的 ValueError 文案透传进 401 body，属对外契约）：

- ``decode_jwt`` / ``encode_jwt`` 签名与 kwargs 不变（``verify_signature`` /
  ``secret``）⇒ 中间件与既有测试零改；
- 中文错误文案逐条对码保持（见各 raise 站点）；
- alg=none mock 分支用 PyJWT 原生表达（``key=None, algorithm="none"``），
  产出与手写版同形（空签名段）；
- **exp 语义**：手写版完全不看 exp（契约 v1.1 §C1 亦无规定）⇒ 显式
  ``verify_exp: False`` 保持现状。启用过期校验须先出契约 v1.2
  （exp 必填/leeway/时钟源），不在本模块悄咪咪开——登记为已知边界。
- 短 HMAC 密钥（<32B）会触发 PyJWT ``InsecureKeyLengthWarning``：**刻意不
  suppress**，那是真实安全信号（仓内无 filterwarnings=error 配置）。

红线遵守：PyJWT 不进 agent-core（ARCHITECTURE.md §4.1）；exhibition 侧引入
与 agent-runtime [identity] extra 同先例。
"""

from __future__ import annotations

import base64
import json
from typing import Any

import jwt
from agent_core.logging import get_logger
from jwt import PyJWTError

logger = get_logger(__name__)

# STRICT 档唯一允许的签名算法。钉死 ⇒ alg=none / RS256 混淆在验签路径结构性拒绝
# （手写版是"空签名段碰巧比对失败"，PyJWT 是算法白名单，判据强度只增不减）。
_STRICT_ALGORITHMS = ["HS256"]


def decode_jwt(token: str, *, verify_signature: bool = False, secret: str | None = None) -> dict[str, Any]:
    """解析 JWT 的 payload claim。

    结构：header.payload.signature（三段 base64url，点分隔）。
    - verify_signature=False（mock 默认）：仅解析 payload，不验签。
    - verify_signature=True：需 secret，HS256 验签（生产由网关/中间件启用）。

    raise ValueError：结构非法 / payload 非 JSON object / 签名无效
    （文案与手写版逐条保持，中间件透传进 401 body）。
    """
    if verify_signature:
        if secret is None:
            raise ValueError("verify_signature=True 但 secret 未提供")
        try:
            payload = jwt.decode(
                token,
                secret,
                algorithms=_STRICT_ALGORITHMS,
                options={"verify_exp": False},  # 见模块 docstring：exp 语义未立契约
            )
        except jwt.InvalidSignatureError as exc:
            # 篡改 / 错钥（手写版同文案）
            raise ValueError("JWT 签名无效") from exc
        except jwt.InvalidAlgorithmError as exc:
            # alg=none 等非 HS256 混入 STRICT 档（手写版碰巧拒，此处结构性拒）
            raise ValueError("JWT 签名无效") from exc
        except jwt.DecodeError as exc:
            # 段数非法 / base64url 坏 / JSON 坏（手写版「JWT 结构非法」同族）
            raise ValueError(f"JWT payload 解析失败：{exc}") from exc
        except PyJWTError as exc:
            raise ValueError(f"JWT 验签失败：{exc}") from exc
    else:
        try:
            payload = jwt.decode(token, options={"verify_signature": False, "verify_exp": False})
        except PyJWTError as exc:
            raise ValueError(f"JWT payload 解析失败：{exc}") from exc

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
    """JWT 编码（PyJWT 实现）。

    - secret 提供：HS256 签名（生产由平台网关签发；本函数供测试/本地复现同形 token）；
    - secret 为 None：alg=none 无签名 mock 版（空签名段，与手写版逐位同形），
      仅供 DEV 档 / demo 使用，verify_signature=False 的解码器可解析。
    """
    if secret is not None:
        return jwt.encode(payload, secret, algorithm="HS256")
    return jwt.encode(payload, key=None, algorithm="none")
