# -*- coding: utf-8 -*-
"""
入站安全护栏纯逻辑（框架无关内核，源自 zhiku M5 security_guard_utils）。

把鉴权 / 限流 / 豁免决策抽为**无 web 依赖的纯函数**，便于单元测试；
``agent_core.guardrails.web.SecurityGuardsMiddleware`` 负责把它们接到 ASGI 请求上。

说明：纯 dict 请求头在测试中需用小写 key（与 starlette Headers 的大小写不敏感行为一致）。

框架无关：仅依赖 stdlib，不 import 任何宿主应用或第三方包。
``DEFAULT_EXEMPT_PATHS`` 为可配置默认值，所有决策函数均接受 ``exempt_paths`` 覆盖。

DUP-1 / CodeQL ``py/weak-sensitive-data-hashing`` 收口：本模块是全仓 **唯一的**
「密钥 → 稳定指纹」实现（``fingerprint``），宿主不得再各自 ``hashlib.sha256(api_key)``
（由 ``scripts/lint_architecture.py`` P6 不变量拦截）。历史四处散点实现语义分裂
（全量 vs ``[:12]`` 48bit 截断、均无服务端 pepper），现已收敛到此。
"""

import hashlib
import hmac
import threading
from typing import Mapping, Optional, Tuple

from agent_core.config import env_str
from agent_core.logging import get_logger

logger = get_logger(__name__)

# 服务端 pepper（HMAC 密钥）：跨部署不可关联性的来源，新增 env 已登记（README 清单）
ENV_SECURITY_PEPPER = "AGENT_PLATFORM_SECURITY_PEPPER"

# 指纹最短十六进制长度（128bit）：身份/会话派生不得低于此值（CodeQL 截断弱点根因）
MIN_FINGERPRINT_HEX = 32

# 会话身份：前缀 + 摘要长度（原 ``[:12]`` 48bit → 128bit，目录名仍远小于文件系统上限）
THREAD_ID_PREFIX = "user-"
THREAD_ID_DIGEST_HEX = 32

# 开发模式（未启用鉴权）的缺省会话
DEV_THREAD_ID = "dev-default-thread"

_pepper_warned = False
_pepper_warn_lock = threading.Lock()


def _pepper() -> str:
    """读取服务端 pepper（每次调用读 env，便于测试注入与运行期显式配置）。"""
    return env_str(ENV_SECURITY_PEPPER, "")


def fingerprint(secret: str, *, length: Optional[int] = None) -> str:
    """
    密钥/敏感标识 → 定长摘要（**全仓唯一实现**，DUP-1 收敛点）。

    ``HMAC-SHA256(pepper, secret)`` 的十六进制摘要，可选截断。相比此前散点的
    裸 ``sha256(api_key)``：① 带服务端 pepper，同一密钥在不同部署下摘要不同
    （跨部署不可关联）；② 截断有下限，杜绝 48bit 弱身份。

    :param secret: 待派生的密钥原文（仅在此处短暂使用，不落入返回值）
    :param length: 返回的十六进制字符数；``None`` 为全量 64 位
    :raises ValueError: ``length`` 不在 ``[MIN_FINGERPRINT_HEX, 64]`` 区间
    """
    if length is not None and not (MIN_FINGERPRINT_HEX <= length <= 64):
        raise ValueError(
            f"length 必须在 {MIN_FINGERPRINT_HEX}~64 之间（128bit~256bit），当前 {length}"
        )
    pepper = _pepper()
    global _pepper_warned
    if not pepper and not _pepper_warned:
        with _pepper_warn_lock:
            if not _pepper_warned:
                _pepper_warned = True
                logger.warning(
                    "[guardrails] %s 未配置：指纹仍可确定性派生，但失去跨部署不可关联性；"
                    "生产部署请设置稳定 pepper（一经使用勿再变更，否则会话身份整体漂移）",
                    ENV_SECURITY_PEPPER,
                )
    digest = hmac.new(pepper.encode("utf-8"), secret.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest if length is None else digest[:length]


def derive_thread_id(api_key: Optional[str]) -> str:
    """
    认证启用期的会话身份：``user-{fingerprint(api_key, 32 hex)}``。

    语义与历史一致（同一密钥稳定、客户端不可指定/猜测他人会话），仅派生强度变更；
    既有落盘会话的迁移见 ``scripts/migrate_thread_identity.py``。
    """
    return f"{THREAD_ID_PREFIX}{fingerprint(api_key or '', length=THREAD_ID_DIGEST_HEX)}"


def legacy_thread_id(api_key: Optional[str]) -> str:
    """
    【仅供一次性迁移/回归测试使用】升级前的弱派生 ``user-{sha256(api_key)[:12]}``。

    业务代码调用即违反 DUP-1 收敛（P6 lint 在本模块白名单内，故仅靠约定约束）；
    保留它是为了让 ``legacy → new`` 映射可计算（否则历史会话目录/检查点无法找回）。
    """
    digest = hashlib.sha256((api_key or "").encode("utf-8")).hexdigest()[:12]
    return f"{THREAD_ID_PREFIX}{digest}"


def extract_api_key_from_headers(headers: Mapping[str, str]) -> str:
    """
    从请求头提取 API Key：优先 ``X-API-Key``，其次 ``Authorization: Bearer <key>``。

    :param headers: 请求头（starlette Headers 大小写不敏感；测试传小写 key 的 dict）
    :return: 规范化后的 key（去首尾空白）；无则空串
    """
    x_key = headers.get("x-api-key", "")
    if x_key:
        return x_key.strip()
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def resolve_client_key(headers: Mapping[str, str], client_host: Optional[str], auth_enabled: bool) -> str:
    """
    解析限流 client 标识（优先 X-API-Key，其次客户端 IP）。

    :param headers: 请求头
    :param client_host: 客户端 IP（request.client.host，可能为 None）
    :param auth_enabled: 是否启用 API Key 鉴权
    :return: 限流桶 key；启用鉴权且有 key 时用 ``fingerprint`` 摘要（避免内存留存明文）
    """
    if auth_enabled:
        provided = extract_api_key_from_headers(headers)
        if provided:
            return f"key:{fingerprint(provided)}"
    ip = (client_host or "").strip() or "unknown"
    return f"ip:{ip}"


# 默认免鉴权 / 免限流路径（健康探针 + 静态页面；浏览器导航无法携带自定义请求头）。
# 可通过各决策函数的 exempt_paths 参数或中间件构造参数覆盖（宿主应用依赖此可配置）。
DEFAULT_EXEMPT_PATHS: Tuple[str, ...] = ("/health", "/chat.html", "/import.html")


def is_health_path(path: str) -> bool:
    """是否健康探针路径（``/health`` 及 ``/health/live``、``/health/ready`` 等子路径）。"""
    return path == "/health" or path.startswith("/health/")


def should_skip_all_guards(path: str, exempt_paths: Tuple[str, ...] = DEFAULT_EXEMPT_PATHS) -> bool:
    """探针 / 静态页面：跳过全部护栏（鉴权 + 限流 + 载荷大小）。"""
    if is_health_path(path):
        return True
    return path in (exempt_paths or ())


def should_skip_auth(path: str, exempt_paths: Tuple[str, ...] = DEFAULT_EXEMPT_PATHS) -> bool:
    """
    免鉴权：除 exempt_paths 外，``/stream/...``（SSE）也免鉴权 ——
    浏览器 EventSource 无法携带自定义请求头（已知限制，宿主 README 应说明）。
    """
    if should_skip_all_guards(path, exempt_paths):
        return True
    return path.startswith("/stream/")


def should_skip_rate_limit(path: str, exempt_paths: Tuple[str, ...] = DEFAULT_EXEMPT_PATHS) -> bool:
    """仅豁免 exempt_paths（探针 / 静态页面）；SSE 仍参与限流（防连接滥用）。"""
    return should_skip_all_guards(path, exempt_paths)


def format_validation_error(errors: list) -> str:
    """
    将 pydantic 校验错误格式化为对外可读文案（含长度上限 / 实际长度，若 ctx 提供）。

    :param errors: ``exc.errors()`` 列表
    :return: 脱敏后的错误信息
    """
    if not errors:
        return "请求参数校验失败"
    first = errors[0]
    loc = ".".join(str(part) for part in first.get("loc", []) if part not in ("body", "query"))
    err_type = first.get("type", "")
    ctx = first.get("ctx") or {}
    if err_type == "string_too_long":
        limit = ctx.get("limit_value", "?")
        actual = ctx.get("actual_length", "?")
        return f"字段 '{loc}' 长度超限（上限 {limit} 字符，当前 {actual} 字符）"
    if err_type == "string_too_short":
        limit = ctx.get("limit_value", "?")
        return f"字段 '{loc}' 长度不足（至少 {limit} 字符）"
    msg = first.get("msg")
    if isinstance(msg, str) and msg:
        return f"字段 '{loc}' 校验失败：{msg}"
    return f"字段 '{loc}' 校验失败"


__all__ = [
    "ENV_SECURITY_PEPPER",
    "MIN_FINGERPRINT_HEX",
    "THREAD_ID_PREFIX",
    "THREAD_ID_DIGEST_HEX",
    "DEV_THREAD_ID",
    "fingerprint",
    "derive_thread_id",
    "legacy_thread_id",
    "extract_api_key_from_headers",
    "resolve_client_key",
    "DEFAULT_EXEMPT_PATHS",
    "is_health_path",
    "should_skip_all_guards",
    "should_skip_auth",
    "should_skip_rate_limit",
    "format_validation_error",
]
