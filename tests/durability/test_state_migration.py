"""V3-6 单测：State Schema Version / Migration。

验证：
- StateSchemaMigrator：注册 / 链式迁移 / 降级拒绝 / 无路径报错；
- Checkpoint.state_schema_version 字段；
- PgCheckpointStore load 时自动迁移（通过 fake pool）。
"""

import time

import pytest
from agent_runtime.planner.durability import Checkpoint
from agent_runtime.planner.durability_pg import PgCheckpointStore
from agent_runtime.state_migration import (
    CURRENT_STATE_SCHEMA_VERSION,
    StateMigrationError,
    StateSchemaMigrator,
    get_default_migrator,
)

# ===== StateSchemaMigrator =====

def test_migrator_no_migration_needed():
    mgr = StateSchemaMigrator()
    result, steps = mgr.migrate({"a": 1}, from_version=1)
    assert result == {"a": 1}
    assert steps == []


def test_migrator_chain_migration():
    mgr = StateSchemaMigrator()
    mgr._target_version = 3
    mgr.register(1, 2, lambda d: {**d, "v2_field": "added"}, "add v2_field")
    mgr.register(2, 3, lambda d: {**d, "v3_field": "added"}, "add v3_field")

    result, steps = mgr.migrate({"a": 1}, from_version=1)
    assert result["a"] == 1
    assert result["v2_field"] == "added"
    assert result["v3_field"] == "added"
    assert len(steps) == 2
    assert steps[0].from_version == 1
    assert steps[1].from_version == 2


def test_migrator_partial_migration():
    mgr = StateSchemaMigrator()
    mgr._target_version = 3
    mgr.register(1, 2, lambda d: {**d, "v2": True}, "v2")
    mgr.register(2, 3, lambda d: {**d, "v3": True}, "v3")

    result, steps = mgr.migrate({"a": 1}, from_version=2)
    assert "v2" not in result
    assert result["v3"] is True
    assert len(steps) == 1


def test_migrator_downgrade_rejected():
    mgr = StateSchemaMigrator()
    mgr._target_version = 1
    with pytest.raises(StateMigrationError, match="降级"):
        mgr.migrate({"a": 1}, from_version=2, to_version=1)


def test_migrator_missing_path():
    mgr = StateSchemaMigrator()
    mgr._target_version = 3
    mgr.register(2, 3, lambda d: d, "noop")
    with pytest.raises(StateMigrationError, match="无注册的迁移路径"):
        mgr.migrate({"a": 1}, from_version=1)


def test_migrator_register_must_be_single_step():
    mgr = StateSchemaMigrator()
    with pytest.raises(StateMigrationError, match="单步递增"):
        mgr.register(1, 3, lambda d: d)


def test_migrator_duplicate_register_rejected():
    mgr = StateSchemaMigrator()
    mgr._target_version = 3
    mgr.register(1, 2, lambda d: d, "first")
    with pytest.raises(StateMigrationError, match="已注册"):
        mgr.register(1, 2, lambda d: d, "second")


def test_migrator_needs_migration():
    mgr = StateSchemaMigrator()
    mgr._target_version = 3
    assert mgr.needs_migration(1)
    assert mgr.needs_migration(2)
    assert not mgr.needs_migration(3)


def test_migrator_registered_steps_audit():
    mgr = StateSchemaMigrator()
    mgr._target_version = 3
    mgr.register(1, 2, lambda d: d, "step 1→2")
    mgr.register(2, 3, lambda d: d, "step 2→3")
    steps = mgr.registered_steps
    assert len(steps) == 2
    assert steps[0].description == "step 1→2"
    assert steps[1].description == "step 2→3"


def test_default_migrator_current_version():
    mgr = get_default_migrator()
    assert mgr.target_version == CURRENT_STATE_SCHEMA_VERSION
    assert not mgr.needs_migration(CURRENT_STATE_SCHEMA_VERSION)


# ===== Checkpoint.state_schema_version =====

def test_checkpoint_default_schema_version():
    cp = Checkpoint("e1", {"n1": "r1"})
    assert cp.state_schema_version == CURRENT_STATE_SCHEMA_VERSION


def test_checkpoint_explicit_schema_version():
    cp = Checkpoint("e1", {"n1": "r1"}, state_schema_version=2)
    assert cp.state_schema_version == 2


def test_checkpoint_to_dict_includes_schema_version():
    cp = Checkpoint("e1", {"n1": "r1"}, state_schema_version=3)
    d = cp.to_dict()
    assert d["state_schema_version"] == 3


# ===== PgCheckpointStore load 自动迁移 =====

def test_pg_checkpoint_load_auto_migrate():
    """PgCheckpointStore load 时自动迁移旧 schema 版本。"""
    from tests.durability.test_pg_durability import _FakePgPool

    pool = _FakePgPool()
    # 手动塞入旧版本 checkpoint（schema_version=1）
    pool.checkpoints["e1"] = {
        "completed": {"n1": {"result": "old"}},
        "updated_at": time.time(),
        "resumable": False,
        "version": 1,
        "generation": 1,
        "state_schema_version": 1,
    }

    migrator = StateSchemaMigrator()
    migrator._target_version = 2
    migrator.register(1, 2, lambda d: {k: {**v, "migrated": True} for k, v in d.items()}, "add migrated flag")

    store = PgCheckpointStore(pool, migrator=migrator)
    import asyncio
    cp = asyncio.run(store.load("e1"))
    assert cp is not None
    assert cp.completed["n1"]["migrated"] is True
    assert cp.state_schema_version == 1  # 原始版本保留


def test_pg_checkpoint_save_load_roundtrip_with_schema_version():
    """save → load 往返保留 state_schema_version。"""
    from tests.durability.test_pg_durability import _FakePgPool

    pool = _FakePgPool()
    store = PgCheckpointStore(pool)

    import asyncio
    cp = Checkpoint("e1", {"n1": "r1"}, state_schema_version=2)
    asyncio.run(store.save(cp))

    loaded = asyncio.run(store.load("e1"))
    assert loaded is not None
    assert loaded.state_schema_version == 2
    assert loaded.completed == {"n1": "r1"}
