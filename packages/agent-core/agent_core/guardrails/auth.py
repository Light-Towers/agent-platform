# -*- coding: utf-8 -*-
"""
入站安全护栏纯逻辑（框架无关内核，源自 zhiku M5 security_guard_utils）。

把鉴权 / 限流 / 豁免决策抽为**无 web 依赖的纯函数**，便于单元测试；
``agent_core.guardrails.web.SecurityGuardsMiddleware`` 负责把它们接到 ASGI 请求上。

说明：纯 dict 请求头在测试中需用小写 key（与 starlette Headers 的大小写不敏感行为一致）。

框架无关：仅依赖 stdlib，不 import 任何宿主应用或第三方包。
``DEFAULT_EXEMPT_PATHS`` 为可配置默认值，所有决策函数均接受 ``exempt_paths`` 覆盖。

DUP-1 / CodeQL ``py/weak-sensitive-data-hashing`` 收口（B7b 全批已闭合）：本模块曾是
全仓**唯一的**「密钥 → 稳定指纹」实现，现三条「凭据 → 摘要」通路已全部拆除，**且实现
本体一并删除** —— 链③ LLM 客户端缓存键（B7b-1，改不透明 slot）、
链② 限流桶（B7b-2，``resolve_client_key`` 改「服务端断言主体优先 → IP 兜底」）、
链① 会话身份（B7b-4，旧 ``derive_thread_id`` 形参为 ``api_key`` → 现
``resolve_thread_identity(principal)``：入参是服务端已断言的主体明文，**不做任何摘要**）。
**本模块不再包含 ``hashlib`` / ``hmac`` 调用**：凭据不参与任何派生，宿主也不得再手写
（由 ``scripts/lint_architecture.py`` P6 不变量拦截：裸哈希白名单已空 + 「凭据→摘要」入口名黑名单）。

为何删函数而非只改调用方（CodeQL 取证结论，勿按字面理解「只要没人调就安全」）：
该规则的 Expensive 分支把**形参名即视为源**（``api_key`` 命中 password 启发式），
故只要「``api_key`` 形参 → 摘要位」这条函数体内通路还在，告警就在 —— 与外部是否
调用无关。改名消警是纯 gaming（被摘要的仍是凭据），唯一诚实出路是让会话身份与限流
都不再从凭据派生。

旧格式常量（``user-`` 前缀）与 ``legacy_thread_id`` 已随 B7b-5 删除：历史会话标识**本已
存在于数据里**（``updated/session_*/`` 目录名、``checkpoints.thread_id`` 行），迁移改为
**枚举现存标识后重挂**，不再从密钥反算（见根 ``scripts/migrate_thread_identity.py``）。

会话 id 前缀已由 ``user-`` 改为 ``tenant-``（主体是租户而非用户，名字要反映真实
主体）：新格式与两代凭据摘要（``user-<12hex>`` / ``user-<32hex>``）在数据面上
天然可分，旧数据的枚举式重挂因此不需长度/字符集启发式。
"""

import re
from typing import Mapping, Optional, Tuple

# 会话身份前缀：主体已按「租户级」断言（Q1=(a)），故前缀如实写 ``tenant-``。
# 与两代凭据摘要形态（``user-<12hex>`` / ``user-<32hex>``）在数据面可分，
# 迁移判别式因此不需启发式（见 scripts/migrate_thread_identity.py）。
THREAD_ID_PREFIX = "tenant-"

# 合法主体字符集：ASCII 字母数字开头，后续允许 ``.`` ``_`` ``-``（总长 ≤ 64）。
# 必须落在 kernel ``guardrails.fs.safe_filename`` 的**恒等集**内：该白名单为
# ``[^\w.\- ]``，会把 ``:`` ``/`` ``\\`` ``*`` ``?`` ``<`` ``>`` ``|`` 等一律替换为 ``_``，
# 于是租户 ``a:b`` 与 ``a_b`` 落盘同目录（会话互串）。内核**不做有损清洗**
# （清洗 = 制造碰撞面），不符即 fail-fast：宁可在首请求报错，不可静默共用目录。
_PRINCIPAL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

# 开发模式（未启用鉴权）的缺省会话
DEV_THREAD_ID = "dev-default-thread"


def resolve_thread_identity(principal: str) -> str:
    """
    认证启用期的会话身份：``tenant-<服务端断言主体>``（**不做任何摘要**）。

    B7b-4（拆 CodeQL ``py/weak-sensitive-data-hashing`` 链①）：旧实现
    ``derive_thread_id``（形参名即 ``api_key``）把调用方凭据当身份熵源——那正是本规则 Expensive 分支
    的实锤通路（形参名即源）。本函数的入参是**已经服务端验签/断言的主体明文**
    （如租户 id），与凭据无任何派生关系；产物可直接入目录名，故不需摘要。

    :param principal: 服务端**已断言**的主体标识（宿主取值点：agent_server 用
        ``server_tenant_id(default)``，联邦用 ``get_tenant_context()``）。
        **严禁传凭据、凭据摘要或客户端可控值**（客户端可指定 = 会话劫持回归）
    :return: ``tenant-<principal>``
    :raises ValueError: 主体为空/全空白，或不在 ``_PRINCIPAL_RE`` 字符集内
        （含会被 ``safe_filename`` 有损改写的字符，如 ``:`` ``/`` 空格）
    """
    bound = (principal or "").strip()
    if not bound:
        raise ValueError(
            "principal 必须为非空服务端断言主体（不得静默落共享会话桶）；"
            "请检查身份断言链路：SINGLE_TENANT / 令牌 tenant_id claim / 部署级 default"
        )
    if not _PRINCIPAL_RE.match(bound):
        raise ValueError(
            "principal 字符集非法（需匹配 ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$）："
            f"当前 {bound!r} 含会被 safe_filename 有损改写或超长的字符，"
            "不同租户可能落同一会话目录；请在宿主侧改用 filename-safe 的租户 slug"
        )
    return f"{THREAD_ID_PREFIX}{bound}"


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


def resolve_client_key(client_host: Optional[str], subject: Optional[str] = None) -> str:
    """
    解析限流 client 标识：**服务端断言主体优先，否则退回客户端 IP**。

    B7b-2（拆 CodeQL ``py/weak-sensitive-data-hashing`` 链②）：旧实现为鉴权启用且带上
    ``X-API-Key``/``Bearer`` 时返回以 ``key:`` 为前缀的凭据指纹桶键——那是「凭据 → 摘要位」
    的实锤通路。本函数**不再读任何请求头**（签名里没有 headers 参数 ⇒ 凭据无法再流进来）。
    隔离粒度上两者不等价，**两面都得知道**：旧实现下同一把部署级密钥的所有客户端共用一个桶
    （一个打满→同密钥其他客户端连带 429）；新实现按 IP/主体独立，但**单客户端换 IP 可重置配额**
    ⇒ 限流强度下降（兜底的是已有的全局窗口与接入后的主体桶，见方案 §4.2 实施补记）。

    :param client_host: 客户端 IP（request.client.host，可能为 None）
    :param subject: 服务端**已断言**的主体标识（如租户 id），由宿主经中间件注入；
                    无断言传 ``None`` ⇒ 退回 IP。**严禁传凭据或其派生值**
    :return: 限流桶 key：``sub:<subject>`` / ``ip:<host>``（无 IP 时 ``ip:unknown``）
    """
    bound = (subject or "").strip()
    if bound:
        return f"sub:{bound}"
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
    "THREAD_ID_PREFIX",
    "DEV_THREAD_ID",
    "resolve_thread_identity",
    "extract_api_key_from_headers",
    "resolve_client_key",
    "DEFAULT_EXEMPT_PATHS",
    "is_health_path",
    "should_skip_all_guards",
    "should_skip_auth",
    "should_skip_rate_limit",
    "format_validation_error",
]
