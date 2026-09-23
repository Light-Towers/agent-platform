"""V3-10 单测：Skill Version / Lifecycle / Compatibility。

验证：
- SkillLifecycle：状态 + callable 判定；
- SkillVersion：解析 / 比较 / 兼容性；
- check_compatibility：checkpoint 版本兼容性检查；
- Skill version/lifecycle 字段。
"""


from agent_runtime.skill_lifecycle import (
    CompatibilityResult,
    SkillLifecycle,
    SkillVersion,
    check_compatibility,
)
from agent_runtime.skills.registry import Skill, SkillKind

# ===== SkillLifecycle =====

def test_lifecycle_callable():
    assert SkillLifecycle.EXPERIMENTAL.callable
    assert SkillLifecycle.STABLE.callable
    assert SkillLifecycle.DEPRECATED.callable
    assert not SkillLifecycle.RETIRED.callable


# ===== SkillVersion =====

def test_version_parse():
    v = SkillVersion.parse("1.2.3")
    assert v.major == 1 and v.minor == 2 and v.patch == 3

    v = SkillVersion.parse("2")
    assert v.major == 2 and v.minor == 0 and v.patch == 0

    v = SkillVersion.parse("v3.1")
    assert v.major == 3 and v.minor == 1


def test_version_str():
    assert str(SkillVersion(1, 2, 3)) == "1.2.3"


def test_version_compatible_same_major():
    v1 = SkillVersion(1, 0, 0)
    v2 = SkillVersion(1, 2, 3)
    v3 = SkillVersion(1, 2, 0)
    assert v2.is_compatible_with(v1)  # 1.2.3 >= 1.0.0
    assert v3.is_compatible_with(v1)  # 1.2.0 >= 1.0.0
    assert not v1.is_compatible_with(v2)  # 1.0.0 < 1.2.3


def test_version_incompatible_different_major():
    v1 = SkillVersion(1, 0, 0)
    v2 = SkillVersion(2, 0, 0)
    assert not v1.is_compatible_with(v2)
    assert not v2.is_compatible_with(v1)


# ===== check_compatibility =====

def test_compat_retired_rejected():
    result = check_compatibility("1.0.0", "1.0.0", SkillLifecycle.RETIRED)
    assert not result
    assert "退役" in result.reason


def test_compat_no_checkpoint_version():
    result = check_compatibility("1.0.0", None)
    assert result
    assert "向后兼容" in result.reason


def test_compat_compatible():
    result = check_compatibility("1.2.0", "1.0.0")
    assert result
    assert "兼容" in result.reason


def test_compat_breaking_change():
    result = check_compatibility("2.0.0", "1.0.0")
    assert not result
    assert "breaking" in result.reason


def test_compat_downgrade():
    result = check_compatibility("1.0.0", "1.2.0")
    assert not result
    assert "降级" in result.reason


def test_compat_with_skill_version_objects():
    result = check_compatibility(SkillVersion(1, 1, 0), SkillVersion(1, 0, 0))
    assert result


def test_compatibility_result_bool():
    assert bool(CompatibilityResult(True))
    assert not bool(CompatibilityResult(False))


# ===== Skill version/lifecycle 字段 =====

def test_skill_default_version_none():
    skill = Skill(
        name="test",
        description="test skill",
        kind=SkillKind.FUNCTION,
        executor=None,  # type: ignore
    )
    assert skill.version is None
    assert skill.lifecycle is None
    assert skill.deprecated_since is None
    assert skill.replaced_by is None


def test_skill_with_version_and_lifecycle():
    skill = Skill(
        name="search",
        description="search skill",
        kind=SkillKind.FUNCTION,
        executor=None,  # type: ignore
        version="1.2.0",
        lifecycle=SkillLifecycle.STABLE,
    )
    assert skill.version == "1.2.0"
    assert skill.lifecycle is SkillLifecycle.STABLE


def test_skill_deprecated():
    skill = Skill(
        name="old_search",
        description="deprecated search",
        kind=SkillKind.FUNCTION,
        executor=None,  # type: ignore
        version="1.0.0",
        lifecycle=SkillLifecycle.DEPRECATED,
        deprecated_since="1.5.0",
        replaced_by="search",
    )
    assert skill.lifecycle is SkillLifecycle.DEPRECATED
    assert skill.deprecated_since == "1.5.0"
    assert skill.replaced_by == "search"
