# -*- coding: utf-8 -*-
"""
兼容 shim：重导出 agent_core.tracing 公共 API，保持旧 import 路径
``from app.core.tracing import ...`` / ``from app.core import tracing`` 不变。

过渡期保留；稳定后各调用点应改为 ``from agent_core.tracing import ...``。
"""

from agent_core.tracing import *  # noqa: F403  —— 重导出，保旧路径
from agent_core.tracing import (  # noqa: F401  —— 显式再导出公共名（便于静态分析）
    generate_request_id,
    get_request_id,
    get_tracer,
    init_tracing,
    is_initialized,
    is_tracing_enabled,
    record_exception,
    set_request_context,
    start_span,
    traced_span,
    user_query_hash,
)
