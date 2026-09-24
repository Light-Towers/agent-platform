"""Skill Version / Lifecycle / Compatibility（V3-10）。

现状（v3 之前）：SkillRegistry 有 name/permissions/composition，
无 version/compatibility/lifecycle/deprecation。Skill 热更新会破坏
Runtime Replay / Checkpoint Recovery / Workflow。

本模块补上：
- ``SkillLifecycle``：生命周期状态（EXPERIMENTAL / STABLE / DEPRECATED / RETIRED）；
- ``SkillVersion``：语义化版本解析与兼容性比较；
- ``check_compatibility``：checkpoint 中的 skill_version 与当前版本兼容性检查。

与 Replay Forensic（V3-9）联动：Trajectory 记录 skill_version，
Recovery 时检查兼容性决定能否 resume。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class SkillLifecycle(str, Enum):
    """Skill 生命周期状态。"""

    EXPERIMENTAL = "experimental"  # 实验性（可能 breaking change）
    STABLE = "stable"  # 稳定（semver 兼容保证）
    DEPRECATED = "deprecated"  # 废弃（仍可用，建议迁移）
    RETIRED = "retired"  # 退役（不可用，注册时拒绝调用）

    @property
    def callable(self) -> bool:
        """是否可调用。"""
        return self is not SkillLifecycle.RETIRED


@dataclass(frozen=True)
class SkillVersion:
    """语义化版本（major.minor.patch）。"""

    major: int
    minor: int = 0
    patch: int = 0

    @classmethod
    def parse(cls, version: str) -> SkillVersion:
        """解析 ``"1.2.3"`` → ``SkillVersion(1, 2, 3)``。"""
        parts = version.strip().lstrip("v").split(".")
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
        return cls(major, minor, patch)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def is_compatible_with(self, other: SkillVersion) -> bool:
        """向后兼容：同 major 且 self >= other（新版本能读旧版本的 checkpoint）。

        不同 major = breaking change = 不兼容。
        """
        return self.major == other.major and (
            (self.major, self.minor, self.patch) >= (other.major, other.minor, other.patch)
        )


@dataclass
class CompatibilityResult:
    """兼容性检查结果。"""

    compatible: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.compatible


def check_compatibility(
    current_version: str | SkillVersion,
    checkpoint_version: str | SkillVersion | None,
    current_lifecycle: SkillLifecycle = SkillLifecycle.STABLE,
) -> CompatibilityResult:
    """检查 checkpoint 中的 skill_version 与当前版本是否兼容。

    - checkpoint_version is None = 旧 checkpoint 无版本信息 → 兼容（向后兼容）；
    - 同 major 且 current >= checkpoint → 兼容；
    - 不同 major → 不兼容（breaking change）；
    - RETIRED → 不兼容（不可调用）。
    """
    if current_lifecycle is SkillLifecycle.RETIRED:
        return CompatibilityResult(False, "skill 已退役（retired）")

    if checkpoint_version is None:
        return CompatibilityResult(True, "旧 checkpoint 无版本信息，向后兼容")

    cur = current_version if isinstance(current_version, SkillVersion) else SkillVersion.parse(current_version)
    chk = checkpoint_version if isinstance(checkpoint_version, SkillVersion) else SkillVersion.parse(checkpoint_version)

    if cur.is_compatible_with(chk):
        return CompatibilityResult(True, f"兼容：current={cur} >= checkpoint={chk}")

    if cur.major != chk.major:
        return CompatibilityResult(
            False,
            f"breaking change：major 不匹配 current={cur.major} vs checkpoint={chk.major}",
        )

    return CompatibilityResult(
        False,
        f"版本降级：current={cur} < checkpoint={chk}",
    )


__all__ = [
    "SkillLifecycle",
    "SkillVersion",
    "CompatibilityResult",
    "check_compatibility",
]
