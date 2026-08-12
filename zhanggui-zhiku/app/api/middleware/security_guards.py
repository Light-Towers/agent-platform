# -*- coding: utf-8 -*-
"""
兼容 shim：重导出 agent_core.guardrails.web.SecurityGuardsMiddleware，保持旧 import 路径不变。

过渡期保留；稳定后调用点应改为 ``from agent_core.guardrails.web import SecurityGuardsMiddleware``。

注意：新版中间件通过构造参数 ``error_response`` 注入统一错误响应构造器（替代原
``app.api.errors.error_response`` 的硬依赖）。zhiku 在 app/main.py 实例化时已传入
``app.api.errors.error_response``，业务行为保持不变。
"""

from agent_core.guardrails.web import SecurityGuardsMiddleware  # noqa: F401
