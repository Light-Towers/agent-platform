"""输入 guardrail：PII 脱敏 + prompt injection 检测。

实现已下沉为 agent-core 共享内核（零依赖），见
``agent_core.guardrails.input_guard``。本模块仅作兼容 re-export，
保证既有 ``from gateway.input_guard import guard_input`` 调用方零改动。
"""

from agent_core.guardrails.input_guard import (  # noqa: F401
    detect_injection,
    detect_pii,
    guard_input,
    redact_pii,
)

__all__ = ["guard_input", "detect_pii", "redact_pii", "detect_injection"]
