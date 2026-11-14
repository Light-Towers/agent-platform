# -*- coding: utf-8 -*-
"""统一错误响应工具（兼容 re-export 层）。

``ERROR_CODES`` / ``error_code_for_status`` / ``error_body`` 已于 2026-10 上提到
``agent_core.guardrails.errors``（canonical 单一实现，见该模块 docstring 的迁移说明）。

本模块仅作**过渡期 re-export**，避免改动既有
``from knowledge_service.utils.error_response_utils import ...`` 调用点
（``api/errors.py``、``tests/unit/test_security_guards.py``）。

**不要在此重新定义这些符号**——那正是 DUP-2 要消除的重复实现；所有语义以
``agent_core.guardrails.errors`` 为准（如 ``422`` 映射为 ``VALIDATION_ERROR`` 而非旧的
``UNPROCESSABLE_ENTITY``，与 ks 自身的 validation handler 硬编码值一致）。
"""

from agent_core.guardrails.errors import (
    ERROR_CODES,
    error_body,
    error_code_for_status,
)

__all__ = ["ERROR_CODES", "error_code_for_status", "error_body"]
