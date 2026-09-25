# -*- coding: utf-8 -*-
"""
兼容 shim：重导出 agent_core.guardrails.ratelimit.SlidingWindowRateLimiter，保持旧 import 路径不变。

过渡期保留；稳定后调用点应改为 ``from agent_core.guardrails.ratelimit import SlidingWindowRateLimiter``。
"""

from agent_core.guardrails.ratelimit import SlidingWindowRateLimiter  # noqa: F401
