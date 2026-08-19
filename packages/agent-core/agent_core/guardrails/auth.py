# -*- coding: utf-8 -*-
"""
入站安全护栏纯逻辑（框架无关内核，源自 zhiku M5 security_guard_utils）。

把鉴权 / 限流 / 豁免决策抽为**无 web 依赖的纯函数**，便于单元测试；
``agent_core.guardrails.web.SecurityGuardsMiddleware`` 负责把它们接到 ASGI 请求上。

说明：纯 dict 请求头在测试中需用小写 key（与 starlette Headers 的大小写不敏感行为一致）。

框架无关：仅依赖 stdlib，不 import 任何宿主应用或第三方包。
``DEFAULT_EXEMPT_PATHS`` 为可配置默认值，所有决策函数均接受 ``exempt_paths`` 覆盖。
"""

import hashlib
from typing import Mapping, Optional, Tuple


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
    :return: 限流桶 key；启用鉴权且有 key 时用 sha256 哈希（避免内存留存明文）
    """
    if auth_enabled:
        provided = extract_api_key_from_headers(headers)
        if provided:
            digest = hashlib.sha256(provided.encode("utf-8")).hexdigest()
            return f"key:{digest}"
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
    "extract_api_key_from_headers",
    "resolve_client_key",
    "DEFAULT_EXEMPT_PATHS",
    "is_health_path",
    "should_skip_all_guards",
    "should_skip_auth",
    "should_skip_rate_limit",
    "format_validation_error",
]
