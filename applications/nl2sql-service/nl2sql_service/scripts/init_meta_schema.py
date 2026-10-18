"""初始化/升级 nl2sql 元知识库 schema（版本化 DDL 的应用入口）。

用法：
    python -m nl2sql_service.scripts.init_meta_schema --dsn "$META_DB_DSN"
    python -m nl2sql_service.scripts.init_meta_schema --dry-run      # 只列出将执行的迁移
    python -m nl2sql_service.scripts.init_meta_schema --status       # 读 nl2sql_schema_meta

设计取舍（2026-10-18）：
- **不另造迁移系统**：DDL 全部幂等（`IF NOT EXISTS`），本脚本只按文件名顺序执行
  `migrations/*.up.sql` 并在模板里替换 vector_dim。等出现非幂等 ALTER 时，
  再与 `agent_runtime.migrations.runner` 收敛（它有版本表/checksum/advisory lock）。
- **不默认在 lifespan 里自动建表**：生产库未必给 DDL 权限，自动迁移失败会拖垮启动。
  是否自动化等 Q23 的库权限答案落地后再定，属 opt-in。
- **DSN 打印一律脱敏**（S-4）：只出 `user@host:port/db`。
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

_MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
_PLACEHOLDER = "{{vector_dim}}"
# DDL 与索引构建可能显著超过元知识库默认的 5s statement_timeout
_DDL_STATEMENT_TIMEOUT_MS = 300_000


def load_migrations(vector_dim: int) -> list[tuple[str, str]]:
    """按版本号顺序加载 *.up.sql，并替换 vector_dim 占位符。"""
    files = sorted(_MIGRATIONS_DIR.glob("*.up.sql"))
    if not files:
        raise FileNotFoundError(f"未找到迁移文件：{_MIGRATIONS_DIR}")

    migrations: list[tuple[str, str]] = []
    for path in files:
        sql = path.read_text(encoding="utf-8").replace(_PLACEHOLDER, str(vector_dim))
        if "{{" in sql:
            raise ValueError(f"{path.name} 存在未替换的模板变量，请检查占位符拼写")
        migrations.append((path.name, sql))
    return migrations


async def apply(dsn: str, vector_dim: int) -> list[str]:
    """连接目标库并顺序执行全部迁移；返回已执行的文件名。"""
    from agent_runtime.pool_factory import create_pool

    migrations = load_migrations(vector_dim)
    pool = create_pool(
        dsn=dsn,
        name="meta-schema",
        min_size=1,
        max_size=2,
        timeout=10.0,
        statement_timeout_ms=_DDL_STATEMENT_TIMEOUT_MS,
        read_only=False,
    )
    await pool.open()
    try:
        async with pool.connection() as conn:
            for _name, sql in migrations:
                await conn.execute(sql)
    finally:
        await pool.close()
    return [name for name, _ in migrations]


async def read_status(dsn: str) -> dict[str, str]:
    """读 nl2sql_schema_meta；表不存在时返回空 dict（= 尚未初始化）。"""
    from agent_runtime.pool_factory import create_pool

    pool = create_pool(
        dsn=dsn,
        name="meta-schema-status",
        min_size=1,
        max_size=1,
        timeout=10.0,
        statement_timeout_ms=5000,
        read_only=True,
    )
    await pool.open()
    try:
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = 'nl2sql_schema_meta'"
            )
            if await cur.fetchone() is None:
                return {}
            cur = await conn.execute("SELECT key, value FROM nl2sql_schema_meta")
            # dict_row 下 row 是 dict：按列名取（row[0] 是 tuple 索引，dict 上 KeyError——
            # 与此前 MetaRepository._upsert 的 RETURNING 行同源坑，池统一配 dict_row）
            rows = await cur.fetchall()
            return {row["key"]: row["value"] for row in rows}
    finally:
        await pool.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="初始化 nl2sql 元知识库 schema（幂等）")
    parser.add_argument("--dsn", default="", help="元知识库 DSN；缺省读 Settings.meta_db_dsn")
    parser.add_argument("--vector-dim", type=int, default=0, help="向量维度；缺省读 Settings.vector_dim")
    parser.add_argument("--dry-run", action="store_true", help="只列出将执行的迁移文件，不连库")
    parser.add_argument("--status", action="store_true", help="只读当前 schema 版本")
    args = parser.parse_args(argv)

    from nl2sql_service.clients.postgres_client_manager import redact_dsn
    from nl2sql_service.conf.settings import get_settings

    settings = get_settings()
    dsn = args.dsn or settings.meta_db_dsn
    if not dsn:
        print("错误：未提供 DSN（--dsn 或 META_DB_DSN），元知识库路径未配置")
        return 2
    vector_dim = args.vector_dim or settings.vector_dim

    if args.dry_run:
        migrations = load_migrations(vector_dim)
        print(f"将执行 {len(migrations)} 个迁移（vector_dim={vector_dim}）：")
        for name, sql in migrations:
            print(f"  - {name} ({len(sql)} chars)")
        return 0

    if args.status:
        status = asyncio.run(read_status(dsn))
        if not status:
            print(f"未初始化（无 nl2sql_schema_meta）：{redact_dsn(dsn)}")
            return 1
        print(f"schema 状态：{redact_dsn(dsn)} -> {status}")
        return 0

    applied = asyncio.run(apply(dsn, vector_dim))
    print(f"已应用 {len(applied)} 个迁移（vector_dim={vector_dim}）：{redact_dsn(dsn)}")
    for name in applied:
        print(f"  ✓ {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
