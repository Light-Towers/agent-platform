# -*- coding: utf-8 -*-
"""
安全护栏子包（框架无关内核）。

- ``auth``：鉴权 / 限流 / 豁免决策纯函数（零依赖，可独立单测），含会话身份
  ``resolve_thread_identity``（DUP-1 收敛点，服务端断言主体明文、不做摘要）；
  **不再包含任何「凭据 → 摘要」实现**（B7b 三链已拆，kernel 也不再 import hashlib/hmac）；
- ``fs``：用户可控路径的安全拼接/解析/文件名净化（``safe_join`` /
  ``resolve_within`` / ``safe_filename``，路径注入收敛点）；
- ``errors``：入站统一错误信封与异常脱敏（需 ``from agent_core.guardrails.errors``
  显式导入）——未捕获异常兜底 ``install_error_handlers`` + 出口固定文案
  ``mask_exception_for_client``（堆栈回显收敛点，C 类）；
- ``ratelimit``：滑动窗口限流器（进程内，零第三方依赖）；
- ``web``：ASGI 中间件（需要 starlette，``web`` extra）。

注意：``import agent_core.guardrails`` 仅导入 auth + fs + ratelimit（纯 stdlib），
**不**导入 web，从而无需 starlette 即可使用纯逻辑层。
需要中间件时显式 ``from agent_core.guardrails.web import SecurityGuardsMiddleware``。
"""

from agent_core.guardrails.auth import (
    DEFAULT_EXEMPT_PATHS,
    DEV_THREAD_ID,
    extract_api_key_from_headers,
    format_validation_error,
    is_health_path,
    resolve_client_key,
    resolve_thread_identity,
    should_skip_all_guards,
    should_skip_auth,
    should_skip_rate_limit,
)
from agent_core.guardrails.fs import (
    PathTraversalError,
    resolve_within,
    safe_filename,
    safe_join,
)
from agent_core.guardrails.ratelimit import SlidingWindowRateLimiter, apply_api_rate_limit

__all__ = [
    "DEFAULT_EXEMPT_PATHS",
    "DEV_THREAD_ID",
    "PathTraversalError",
    "resolve_thread_identity",
    "resolve_within",
    "safe_filename",
    "safe_join",
    "extract_api_key_from_headers",
    "format_validation_error",
    "is_health_path",
    "resolve_client_key",
    "should_skip_all_guards",
    "should_skip_auth",
    "should_skip_rate_limit",
    "SlidingWindowRateLimiter",
    "apply_api_rate_limit",
]
