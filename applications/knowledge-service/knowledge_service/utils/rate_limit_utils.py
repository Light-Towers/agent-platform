# -*- coding: utf-8 -*-
"""
兼容 shim：重导出 agent_core.guardrails.ratelimit.apply_api_rate_limit，保持旧 import 路径不变。

过渡期保留；稳定后调用点应改为 ``from agent_core.guardrails.ratelimit import apply_api_rate_limit``。
"""

from agent_core.guardrails.ratelimit import apply_api_rate_limit  # noqa: F401
