"""agent_runtime.migrations — 轻量版 schema 版本迁移系统。

使用方式（由 db.py ensure_schema 内部调用）：
    from agent_runtime.migrations import run_migrations
    applied = await run_migrations(pool)

迁移文件命名约定：
    NNN_description.up.sql   — 正向迁移（必需）
    NNN_description.down.sql — 回滚迁移（可选）

模板变量（SQL 文件内可用）：
    {{vector_dim}} — 向量维度（runner 从 embedder 解析）
"""

from agent_runtime.migrations.base import Migration, discover, max_version, reset
from agent_runtime.migrations.runner import (
    MigrationError,
    get_current_version,
    rollback,
    run_migrations,
)

__all__ = [
    "Migration",
    "MigrationError",
    "discover",
    "get_current_version",
    "max_version",
    "reset",
    "rollback",
    "run_migrations",
]
