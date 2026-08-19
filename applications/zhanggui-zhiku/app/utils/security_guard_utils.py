# -*- coding: utf-8 -*-
"""
兼容 shim：重导出 agent_core.guardrails.auth 公共 API，保持旧 import 路径不变。

过渡期保留；稳定后调用点应改为 ``from agent_core.guardrails.auth import ...``。
"""

from agent_core.guardrails.auth import *  # noqa: F403  —— 重导出，保旧路径
from agent_core.guardrails.auth import (  # noqa: F401  —— 显式再导出公共名（便于静态分析）
    DEFAULT_EXEMPT_PATHS,
    extract_api_key_from_headers,
    format_validation_error,
    is_health_path,
    resolve_client_key,
    should_skip_all_guards,
    should_skip_auth,
    should_skip_rate_limit,
)
