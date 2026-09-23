"""State Schema Version / Migration（V3-6 Layer B）。

现状（v3 之前）：PG checkpoint 是 ``completed JSONB / version / resumable``，
无 ``state_schema_version``，假设 checkpoint 永远兼容当前代码。

本模块补上：
- ``CURRENT_STATE_SCHEMA_VERSION``：当前状态 schema 版本；
- ``StateSchemaMigrator``：migration 链 ``v1 → v2 → ... → vN``，旧 checkpoint 自动迁移；
- ``Checkpoint.state_schema_version``：记录写入时的 schema 版本；
- ``CheckpointStore.load`` 时自动迁移旧版本到当前。

迁移函数签名：``(completed: dict) -> dict``，从版本 N 迁移到 N+1。
migrator 按链式应用：``v1 → v2 → v3`` = ``migrate_1_to_2 ∘ migrate_2_to_3``。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

CURRENT_STATE_SCHEMA_VERSION = 1

MigrationFn = Callable[[dict[str, Any]], dict[str, Any]]


class StateMigrationError(RuntimeError):
    """状态 schema 迁移失败（如无注册的迁移路径、迁移函数抛异常）。"""


@dataclass
class MigrationStep:
    """单步迁移描述（审计用）。"""

    from_version: int
    to_version: int
    description: str


class StateSchemaMigrator:
    """状态 schema 迁移链：``v1 → v2 → ... → vN``。

    用法：
    ```
    migrator = StateSchemaMigrator()
    migrator.register(1, 2, _migrate_v1_to_v2, "add effect_key to completed")
    migrator.register(2, 3, _migrate_v2_to_v3, "rename node_id format")

    # load 时
    completed = migrator.migrate(checkpoint.completed, checkpoint.state_schema_version)
    ```
    """

    def __init__(self) -> None:
        self._migrations: dict[int, tuple[MigrationFn, MigrationStep]] = {}
        self._target_version: int = CURRENT_STATE_SCHEMA_VERSION

    def register(
        self,
        from_version: int,
        to_version: int,
        fn: MigrationFn,
        description: str = "",
    ) -> None:
        """注册从 ``from_version`` → ``to_version`` 的迁移函数。

        约定 ``to_version == from_version + 1``（链式单步迁移）。
        """
        if to_version != from_version + 1:
            raise StateMigrationError(
                f"迁移必须单步递增：from={from_version} → to={to_version} 不满足 to=from+1"
            )
        if from_version in self._migrations:
            raise StateMigrationError(f"版本 {from_version} 的迁移已注册")
        self._migrations[from_version] = (
            fn,
            MigrationStep(from_version, to_version, description),
        )

    @property
    def target_version(self) -> int:
        return self._target_version

    @property
    def registered_steps(self) -> list[MigrationStep]:
        """已注册的迁移步骤（审计用）。"""
        return [entry[1] for _, entry in sorted(self._migrations.items())]

    def migrate(
        self,
        completed: dict[str, Any],
        from_version: int,
        to_version: int | None = None,
    ) -> tuple[dict[str, Any], list[MigrationStep]]:
        """把 ``completed`` 从 ``from_version`` 迁移到 ``to_version``（默认当前版本）。

        返回 ``(migrated_completed, applied_steps)``。
        ``from_version == to_version`` 时原样返回（无迁移）。
        """
        target = to_version if to_version is not None else self._target_version
        if from_version == target:
            return completed, []
        if from_version > target:
            raise StateMigrationError(
                f"不支持降级迁移：from={from_version} > to={target}"
            )

        result = completed
        applied: list[MigrationStep] = []
        cur = from_version
        while cur < target:
            entry = self._migrations.get(cur)
            if entry is None:
                raise StateMigrationError(
                    f"无注册的迁移路径：版本 {cur} → {cur + 1}（目标 {target}）"
                )
            fn, step = entry
            try:
                result = fn(result)
            except Exception as e:  # noqa: BLE001
                raise StateMigrationError(
                    f"迁移失败：版本 {cur} → {cur + 1}: {e}"
                ) from e
            applied.append(step)
            cur += 1

        logger.info(
            "state schema migrated: v%s → v%s, %d steps",
            from_version, target, len(applied),
        )
        return result, applied

    def needs_migration(self, from_version: int) -> bool:
        """是否需要迁移到当前版本。"""
        return from_version < self._target_version


_default_migrator = StateSchemaMigrator()


def get_default_migrator() -> StateSchemaMigrator:
    """全局默认 migrator（无注册迁移时 v1 = current，原样返回）。"""
    return _default_migrator


__all__ = [
    "CURRENT_STATE_SCHEMA_VERSION",
    "StateMigrationError",
    "MigrationStep",
    "StateSchemaMigrator",
    "get_default_migrator",
]
