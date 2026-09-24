"""Schema migration runner（P1-4 轻量版）。

核心职责：
1. 确保 schema_migrations 元表存在；
2. 通过 pg_advisory_xact_lock 实现跨实例互斥；
3. 检测当前 DB 版本 → 按序读取并执行 .sql 文件 → 记录版本；
4. 支持 baseline stamp（兼容已有业务表但无版本记录的存量库）。

模板变量：
- {{vector_dim}}: 由 runner 统一解析并替换（embedder → fallback 512）。

依赖：psycopg AsyncConnectionPool（项目已有），零新增。
"""

from __future__ import annotations

import logging
from typing import Any

from agent_runtime.migrations.base import Migration, discover

logger = logging.getLogger(__name__)

# advisory lock key（全局唯一常量，与 execution_scheduler 的 _SLOT_LOCK_KEY 不冲突）
_MIGRATION_LOCK_KEY = 0xCAFE0001

# 用于检测存量库是否已有业务表（排除 schema_migrations 本身）
_CHECK_EXISTING_TABLE = """
SELECT 1 FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name = 'chunks'
LIMIT 1
"""

_CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    checksum   TEXT NOT NULL DEFAULT ''
);
"""

_INSERT_MIGRATION_RECORD = """
INSERT INTO schema_migrations (version, name, checksum)
VALUES (%s, %s, %s)
ON CONFLICT (version) DO NOTHING
"""

_SELECT_MAX_VERSION = "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"


class MigrationError(RuntimeError):
    """迁移执行失败（事务已回滚）。"""


async def _get_vector_dim() -> int:
    """从 embedder 派生向量维度（单一事实源）。"""
    try:
        from agent_core.memory.embedder import get_embedder

        dim = get_embedder().dim
        logger.debug("migrations runner: vector_dim from embedder = %d", dim)
        return dim
    except (ImportError, RuntimeError, AttributeError) as e:
        logger.warning("migrations runner: embedder unavailable (%s), fallback dim=512", e)
        return 512


async def run_migrations(pool: Any) -> list[Migration]:
    """在 advisory lock 保护下应用所有 pending migrations。

    Args:
        pool: psycopg_pool.AsyncConnectionPool 实例。

    Returns:
        本次实际应用的 migration 列表（空 = 已是最新）。

    Raises:
        MigrationError: 某条迁移 SQL 执行失败，该条事务已回滚。
    """
    migrations = discover()
    if not migrations:
        logger.warning("run_migrations: no migrations discovered, skipping")
        return []

    vector_dim = await _get_vector_dim()
    applied: list[Migration] = []

    async with pool.connection() as conn:
        # 1. 确保元表存在（自身幂等，无事务保护需求）
        await conn.execute(_CREATE_MIGRATIONS_TABLE)

        # 2. 获取 advisory 事务锁 + 读取版本 + 应用迁移在同一事务内
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(%s)", (_MIGRATION_LOCK_KEY,))

            # 3. 读当前版本
            cur = await conn.execute(_SELECT_MAX_VERSION)
            row = await cur.fetchone()
            current_version = row[0] if row else 0

            # 4. Baseline stamp：存量库有业务表但无版本记录 → mark baseline 已应用
            if current_version == 0:
                stamped = await _try_baseline_stamp(conn, migrations)
                if stamped:
                    current_version = stamped[0]
                    applied.extend(stamped[1])

            # 5. 应用 pending
            pending = [m for m in migrations if m.version > current_version]
            if not pending:
                logger.debug("run_migrations: already at version %d, nothing to do", current_version)
                return applied

            logger.info("run_migrations: applying %d pending (current v%d)", len(pending), current_version)
            for m in pending:
                sql = _resolve_templates_sync(m.read_up(), vector_dim=vector_dim)
                try:
                    await conn.execute(sql)
                except Exception as e:
                    raise MigrationError(
                        f"migration v{m.version} ({m.name!r}) failed: {e}"
                    ) from e
                await conn.execute(
                    _INSERT_MIGRATION_RECORD,
                    (m.version, m.name, m.checksum()),
                )
                logger.info("  \u2713 v%d %s", m.version, m.name)
                applied.append(m)

    return applied


def _resolve_templates_sync(sql: str, *, vector_dim: int) -> str:
    """同步模板替换（SQL 文件内 {{vector_dim}} → 实际值）。"""
    return sql.replace("{{vector_dim}}", str(vector_dim))


async def _try_baseline_stamp(
    conn: Any, migrations: list[Migration]
) -> tuple[int, list[Migration]] | None:
    """存量库检测：有业务表但 schema_migrations 为空 → 仅 stamp baseline。

    策略：只 stamp version=1（全量建表）为已应用，跳过重跑 CREATE TABLE。
    v2+ 增量迁移（ALTER ADD COLUMN IF NOT EXISTS）仍正常 apply，
    因为存量库可能缺失后加的列。
    """
    cur = await conn.execute(_CHECK_EXISTING_TABLE)
    existing = await cur.fetchone()
    if not existing:
        return None  # 全新库，需要跑 baseline migration

    # 只 stamp version <= 1 的 baseline migration
    baseline_migrations = [m for m in migrations if m.version <= 1]
    if not baseline_migrations:
        return None

    stamped = []
    for m in baseline_migrations:
        await conn.execute(
            _INSERT_MIGRATION_RECORD,
            (m.version, m.name, "stamped"),
        )
        stamped.append(m)

    max_v = max(m.version for m in stamped)
    logger.info(
        "run_migrations: baseline stamp — existing DB marked baseline as v%d (%d stamped, v2+ will apply)",
        max_v,
        len(stamped),
    )
    return (max_v, stamped)


async def rollback(pool: Any, *, target_version: int) -> list[Migration]:
    """回滚到指定版本（按 version 降序执行 down SQL）。

    Args:
        pool: 连接池。
        target_version: 回滚到的目标版本（含），大于此版本的都 down。

    Returns:
        已回滚的 migration 列表。
    """
    migrations = discover()
    to_rollback = sorted(
        [m for m in migrations if m.version > target_version and m.down_sql is not None],
        key=lambda m: m.version,
        reverse=True,
    )
    if not to_rollback:
        logger.info("rollback: no reversible migrations above v%d", target_version)
        return []

    rolled_back: list[Migration] = []
    async with pool.connection() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(%s)", (_MIGRATION_LOCK_KEY,))
            for m in to_rollback:
                down_sql = m.read_down()
                if down_sql is None:
                    continue
                down_sql = _resolve_templates_sync(down_sql, vector_dim=512)
                try:
                    await conn.execute(down_sql)
                except Exception as e:
                    raise MigrationError(
                        f"rollback v{m.version} ({m.name!r}) failed: {e}"
                    ) from e
                # 删除版本记录
                await conn.execute(
                    "DELETE FROM schema_migrations WHERE version = %s",
                    (m.version,),
                )
                logger.info("  \u2193 rolled back v%d %s", m.version, m.name)
                rolled_back.append(m)

    return rolled_back


async def get_current_version(pool: Any) -> int:
    """查询当前 schema 版本（健康检查/调试用）。"""
    async with pool.connection() as conn:
        await conn.execute(_CREATE_MIGRATIONS_TABLE)
        cur = await conn.execute(_SELECT_MAX_VERSION)
        row = await cur.fetchone()
        return row[0] if row else 0


__all__ = ["run_migrations", "rollback", "get_current_version", "MigrationError"]
