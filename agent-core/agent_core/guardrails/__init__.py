# -*- coding: utf-8 -*-
"""
安全护栏子包（框架无关内核）。

- ``auth``：鉴权 / 限流 / 豁免决策纯函数（零依赖，可独立单测）；
- ``ratelimit``：滑动窗口限流器（进程内，零第三方依赖）；
- ``web``：ASGI 中间件（需要 starlette，``web`` extra）。

注意：``import agent_core.guardrails`` 仅导入 auth + ratelimit（纯 stdlib），
**不**导入 web，从而无需 starlette 即可使用纯逻辑层。
需要中间件时显式 ``from agent_core.guardrails.web import SecurityGuardsMiddleware``。
"""

from agent_core.guardrails.auth import (
    DEFAULT_EXEMPT_PATHS,
    extract_api_key_from_headers,
    format_validation_error,
    is_health_path,
    resolve_client_key,
    should_skip_all_guards,
    should_skip_auth,
    should_skip_rate_limit,
)
from agent_core.guardrails.ratelimit import SlidingWindowRateLimiter, apply_api_rate_limit

__all__ = [
    "DEFAULT_EXEMPT_PATHS",
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
