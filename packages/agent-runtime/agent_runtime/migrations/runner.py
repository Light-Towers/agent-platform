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

# baseline 的关键表集合。只有完整存在时才允许把 v1 标记为已应用；
# 仅检查 chunks 会把“半初始化/损坏”的数据库误判为完整存量库。
_BASELINE_REQUIRED_TABLES = (
    "chunks",
    "memories",
    "semantic_cache",
    "sql_ddl",
    "sql_docs",
    "sql_examples",
    "admission_queue",
    "revert_audit",
    "mcp_call_audit",
    "execution_checkpoints",
    "idempotency_keys",
    "execution_leases",
    "admission_slots",
    "side_effects",
    "execution_events",
    "trajectories",
    "execution_status",
    "awaitable_tasks",
    "execution_queue",
    "budget_usage",
    "budget_limits",
    "cost_records",
    "episodic_memories",
    "procedural_memories",
)

_CHECK_EXISTING_TABLES = """
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name = ANY(%s)
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

_UPDATE_MIGRATION_CHECKSUM = "UPDATE schema_migrations SET checksum = %s WHERE version = %s"

# 旧版 runner 在 baseline stamp 时写入的字面量哨兵 "stamped"（及列默认值 ''）。
# 这类记录无法与文件 checksum 比对，视为"未知来源"，首次启动时用文件真实
# checksum 回填（而非判死），兼容升级前已被旧代码 stamp 的存量库。
_LEGACY_CHECKSUM_SENTINELS = frozenset({"stamped", ""})

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

            # 3. 校验已应用 migration 的 checksum，防止 SQL 文件被静默修改。
            await _validate_applied_checksums(conn, migrations)

            # 4. 读当前版本
            cur = await conn.execute(_SELECT_MAX_VERSION)
            row = await cur.fetchone()
            current_version = row[0] if row else 0

            # 5. Baseline stamp：存量库有完整 baseline 表但无版本记录 → mark baseline 已应用
            if current_version == 0:
                stamped = await _try_baseline_stamp(conn, migrations)
                if stamped:
                    current_version = stamped[0]
                    applied.extend(stamped[1])

            # 6. 应用 pending
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


async def _validate_applied_checksums(conn: Any, migrations: list[Migration]) -> None:
    """校验已应用 migration 的文件 checksum，发现漂移立即失败。

    兼容历史：旧版 stamp 写入的哨兵值（"stamped" / 空串）无法比对，
    在同事务内回填为文件真实 checksum 并告警，不视为漂移。
    注意：checksum 基于未渲染 {{vector_dim}} 的原始文件字节（见 base.py），
    更换 embedder 维度不会触发漂移；跨平台字节稳定性由 .gitattributes
    （* text=auto eol=lf）保证，勿改为对渲染后内容取 hash。
    """
    cur = await conn.execute(
        "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
    )
    rows = await cur.fetchall()
    by_version = {row[0]: row for row in rows}

    for migration in migrations:
        row = by_version.get(migration.version)
        if row is None:
            continue
        recorded = row[2]
        expected = migration.checksum()
        if recorded == expected:
            continue
        if recorded in _LEGACY_CHECKSUM_SENTINELS:
            await conn.execute(_UPDATE_MIGRATION_CHECKSUM, (expected, migration.version))
            logger.warning(
                "migration v%d (%s): legacy checksum %r backfilled from file checksum",
                migration.version,
                migration.name,
                recorded,
            )
            continue
        raise MigrationError(
            f"migration checksum mismatch for v{migration.version} "
            f"({migration.name!r}): database={recorded!r}, file={expected!r}. "
            "If the SQL file was legitimately edited, repair with: "
            "UPDATE schema_migrations SET checksum = <file checksum> WHERE version = "
            f"{migration.version}."
        )


async def _try_baseline_stamp(
    conn: Any, migrations: list[Migration]
) -> tuple[int, list[Migration]] | None:
    """存量库检测：有完整 baseline 表但 schema_migrations 为空 → stamp baseline。

    只在 baseline 所要求的全部关键表都存在时 stamp v1。
    若只存在部分表，说明数据库可能处于半初始化/损坏状态，直接失败，
    避免跳过 baseline migration 后永久遗留缺失表。
    """
    cur = await conn.execute(
        _CHECK_EXISTING_TABLES,
        (_BASELINE_REQUIRED_TABLES,),
    )
    rows = await cur.fetchall()
    existing = {row[0] for row in rows}

    if not existing:
        return None

    missing = sorted(set(_BASELINE_REQUIRED_TABLES) - existing)
    if missing:
        raise MigrationError(
            "existing database has an incomplete baseline schema; "
            f"missing tables: {', '.join(missing)}. "
            "Refusing to stamp v1; inspect/repair the database before migration. "
            "Diagnose with: SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name; "
            "then apply the missing DDL from 001_baseline.up.sql or stamp manually."
        )

    baseline_migrations = [m for m in migrations if m.version <= 1]
    if not baseline_migrations:
        return None

    stamped = []
    for m in baseline_migrations:
        await conn.execute(
            _INSERT_MIGRATION_RECORD,
            (m.version, m.name, m.checksum()),
        )
        stamped.append(m)

    max_v = max(m.version for m in stamped)
    logger.info(
        "run_migrations: baseline stamp — existing DB verified against required tables "
        "(v%d, %d stamped; v2+ will apply)",
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
