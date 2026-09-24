"""State Schema Migration 测试（V3 Phase 4）。

覆盖 StateSchemaMigrator 的链式迁移 / needs_migration / 异常路径。
"""

from __future__ import annotations

import pytest

from agent_runtime.state_migration import (
    CURRENT_STATE_SCHEMA_VERSION,
    StateMigrationError,
    StateSchemaMigrator,
    get_default_migrator,
)


def test_current_version_is_1():
    assert CURRENT_STATE_SCHEMA_VERSION == 1


def test_no_migration_needed():
    migrator = StateSchemaMigrator()
    completed = {"node1": "result1"}
    result, steps = migrator.migrate(completed, from_version=1, to_version=1)
    assert result == completed
    assert steps == []


def test_needs_migration():
    migrator = StateSchemaMigrator()
    assert not migrator.needs_migration(1)
    assert migrator.needs_migration(0)


def test_single_step_migration():
    migrator = StateSchemaMigrator()

    def migrate_1_to_2(completed):
        result = dict(completed)
        result["__schema_v2__"] = True
        return result

    migrator.register(1, 2, migrate_1_to_2, "add schema v2 marker")
    completed = {"node1": "result1"}
    result, steps = migrator.migrate(completed, from_version=1, to_version=2)
    assert result["node1"] == "result1"
    assert result["__schema_v2__"] is True
    assert len(steps) == 1


def test_chained_migration():
    migrator = StateSchemaMigrator()

    def migrate_1_to_2(completed):
        result = dict(completed)
        result["v2"] = True
        return result

    def migrate_2_to_3(completed):
        result = dict(completed)
        result["v3"] = True
        return result

    migrator.register(1, 2, migrate_1_to_2, "v1 → v2")
    migrator.register(2, 3, migrate_2_to_3, "v2 → v3")

    completed = {"node1": "result1"}
    result, steps = migrator.migrate(completed, from_version=1, to_version=3)
    assert result["node1"] == "result1"
    assert result["v2"] is True
    assert result["v3"] is True
    assert len(steps) == 2


def test_migration_error_on_missing_step():
    migrator = StateSchemaMigrator()
    completed = {"node1": "result1"}
    with pytest.raises(StateMigrationError):
        migrator.migrate(completed, from_version=1, to_version=2)


def test_migration_error_on_downgrade():
    migrator = StateSchemaMigrator()
    completed = {"node1": "result1"}
    with pytest.raises(StateMigrationError):
        migrator.migrate(completed, from_version=2, to_version=1)


def test_registered_steps():
    migrator = StateSchemaMigrator()

    def noop(completed):
        return completed

    migrator.register(1, 2, noop, "first")
    migrator.register(2, 3, noop, "second")
    steps = migrator.registered_steps
    assert len(steps) == 2
    assert steps[0].from_version == 1
    assert steps[0].to_version == 2
    assert steps[1].from_version == 2
    assert steps[1].to_version == 3


def test_default_migrator_no_migrations():
    migrator = get_default_migrator()
    completed = {"node1": "result1"}
    result, steps = migrator.migrate(completed, from_version=1, to_version=1)
    assert result == completed
    assert steps == []


def test_register_must_be_single_step():
    migrator = StateSchemaMigrator()

    def noop(completed):
        return completed

    with pytest.raises(StateMigrationError):
        migrator.register(1, 3, noop, "skip v2")
