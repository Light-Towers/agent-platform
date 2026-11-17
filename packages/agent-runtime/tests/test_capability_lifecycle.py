"""V3-10 单测：Capability Version / Lifecycle / Compatibility。

验证：
- CapabilityLifecycle：状态 + callable 判定；
- CapabilityVersion：解析 / 比较 / 兼容性；
- check_compatibility：checkpoint 版本兼容性检查；
- Capability version/lifecycle 字段。
"""


from agent_runtime.capabilities.registry import Capability, CapabilityKind
from agent_runtime.capability_lifecycle import (
    CapabilityLifecycle,
    CapabilityVersion,
    CompatibilityResult,
    check_compatibility,
)

# ===== CapabilityLifecycle =====

def test_lifecycle_callable():
    assert CapabilityLifecycle.EXPERIMENTAL.callable
    assert CapabilityLifecycle.STABLE.callable
    assert CapabilityLifecycle.DEPRECATED.callable
    assert not CapabilityLifecycle.RETIRED.callable


# ===== CapabilityVersion =====

def test_version_parse():
    v = CapabilityVersion.parse("1.2.3")
    assert v.major == 1 and v.minor == 2 and v.patch == 3

    v = CapabilityVersion.parse("2")
    assert v.major == 2 and v.minor == 0 and v.patch == 0

    v = CapabilityVersion.parse("v3.1")
    assert v.major == 3 and v.minor == 1


def test_version_str():
    assert str(CapabilityVersion(1, 2, 3)) == "1.2.3"


def test_version_compatible_same_major():
    v1 = CapabilityVersion(1, 0, 0)
    v2 = CapabilityVersion(1, 2, 3)
    v3 = CapabilityVersion(1, 2, 0)
    assert v2.is_compatible_with(v1)  # 1.2.3 >= 1.0.0
    assert v3.is_compatible_with(v1)  # 1.2.0 >= 1.0.0
    assert not v1.is_compatible_with(v2)  # 1.0.0 < 1.2.3


def test_version_incompatible_different_major():
    v1 = CapabilityVersion(1, 0, 0)
    v2 = CapabilityVersion(2, 0, 0)
    assert not v1.is_compatible_with(v2)
    assert not v2.is_compatible_with(v1)


# ===== check_compatibility =====

def test_compat_retired_rejected():
    result = check_compatibility("1.0.0", "1.0.0", CapabilityLifecycle.RETIRED)
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


def test_compat_with_capability_version_objects():
    result = check_compatibility(CapabilityVersion(1, 1, 0), CapabilityVersion(1, 0, 0))
    assert result


def test_compatibility_result_bool():
    assert bool(CompatibilityResult(True))
    assert not bool(CompatibilityResult(False))


# ===== Capability version/lifecycle 字段 =====

def test_capability_default_version_none():
    capability = Capability(
        name="test",
        description="test capability",
        kind=CapabilityKind.FUNCTION,
        executor=None,  # type: ignore
    )
    assert capability.version is None
    assert capability.lifecycle is None
    assert capability.deprecated_since is None
    assert capability.replaced_by is None


def test_capability_with_version_and_lifecycle():
    capability = Capability(
        name="search",
        description="search capability",
        kind=CapabilityKind.FUNCTION,
        executor=None,  # type: ignore
        version="1.2.0",
        lifecycle=CapabilityLifecycle.STABLE,
    )
    assert capability.version == "1.2.0"
    assert capability.lifecycle is CapabilityLifecycle.STABLE


def test_capability_deprecated():
    capability = Capability(
        name="old_search",
        description="deprecated search",
        kind=CapabilityKind.FUNCTION,
        executor=None,  # type: ignore
        version="1.0.0",
        lifecycle=CapabilityLifecycle.DEPRECATED,
        deprecated_since="1.5.0",
        replaced_by="search",
    )
    assert capability.lifecycle is CapabilityLifecycle.DEPRECATED
    assert capability.deprecated_since == "1.5.0"
    assert capability.replaced_by == "search"
