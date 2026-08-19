"""Capability Registry（Plan-F Phase 1）：能力层中立化。

三执行器 + 统一注册表。Planner（Phase 2）经此调用任意能力，retry/超时/熔断
等 Runtime 边界在 CapabilityRegistry.execute() 收敛（契约点 P1）。
"""

from agent_runtime.capabilities.agent import as_agent_capability
from agent_runtime.capabilities.function import as_function_capability
from agent_runtime.capabilities.registry import (
    Capability,
    CapabilityKind,
    CapabilityNotFoundError,
    CapabilityRegistry,
    DuplicateCapabilityError,
)
from agent_runtime.capabilities.remote import as_remote_capability

__all__ = [
    "Capability",
    "CapabilityKind",
    "CapabilityNotFoundError",
    "CapabilityRegistry",
    "DuplicateCapabilityError",
    "as_agent_capability",
    "as_function_capability",
    "as_remote_capability",
]
