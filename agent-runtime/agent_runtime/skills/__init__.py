"""Skill Registry（Plan-F Phase 1）：能力层中立化。

三执行器 + 统一注册表。Planner（Phase 2）经此调用任意能力，retry/超时/熔断
等 Runtime 边界在 SkillRegistry.execute() 收敛（契约点 P1）。
"""

from agent_runtime.skills.agent import as_agent_skill
from agent_runtime.skills.function import as_function_skill
from agent_runtime.skills.registry import (
    DuplicateSkillError,
    Skill,
    SkillKind,
    SkillNotFoundError,
    SkillRegistry,
)
from agent_runtime.skills.remote import as_remote_skill

__all__ = [
    "Skill",
    "SkillKind",
    "SkillNotFoundError",
    "SkillRegistry",
    "DuplicateSkillError",
    "as_agent_skill",
    "as_function_skill",
    "as_remote_skill",
]
