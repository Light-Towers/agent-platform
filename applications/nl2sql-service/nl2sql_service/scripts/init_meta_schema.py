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
import re
import zlib
from pathlib import Path

_MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
_PLACEHOLDER = "{{vector_dim}}"
# DDL 与索引构建可能显著超过元知识库默认的 5s statement_timeout
_DDL_STATEMENT_TIMEOUT_MS = 300_000

#: 跨实例互斥锁键（#110）。与 agent_runtime.migrations.runner 的 0xCAFE0001 不冲突：
# 由脚本名派生，避免两套 init 将来顺延数字时撞车。xact 级锁覆盖本连接整个隐式事务
# （全部迁移在同一连接上顺序执行），退出即释放。
_INIT_LOCK_KEY = zlib.crc32(b"nl2sql_meta_schema_init") & 0x7FFFFFFF

#: 迁移 DDL 的建表块（本仓四空格缩进列行风格；列名 = 缩进行首词且第二词是类型）
_TABLE_RE = re.compile(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)\s*\((.*?)\n\);", re.S | re.I)
_COLUMN_RE = re.compile(
    r"^(\w+)\s+(?:bigserial|serial|bigint|int|integer|text|boolean|bool|timestamptz|"
    r"timestamp|date|numeric|decimal|real|vector|tsvector|jsonb|json|uuid|bytea)\b",
    re.I,
)


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


def expected_schema(sql_texts: list[str]) -> dict[str, set[str]]:
    """从迁移 SQL 抽取期望的 {表: 列集}（#110 对账的"应然"侧）。

    只认本仓 DDL 的四空格缩进列行风格（列名 = 行首词、第二词是类型）；注释行、
    CONSTRAINT 行、生成列的续行（GENERATED ALWAYS AS ...）天然不匹配类型白名单。
    """
    expected: dict[str, set[str]] = {}
    for text in sql_texts:
        for table, body in _TABLE_RE.findall(text):
            columns = expected.setdefault(table, set())
            for line in body.splitlines():
                line = line.strip()
                if not line or line.startswith("--"):
                    continue
                m = _COLUMN_RE.match(line)
                if m:
                    columns.add(m.group(1).lower())
    return expected


async def verify_applied(conn, expected: dict[str, set[str]]) -> list[str]:
    """对账（#110）：期望表/列 vs information_schema 实况；返回人类可读差异列表。

    连接走 pool_factory（row_factory=dict_row）⇒ 行是 dict，按列名取。
    """
    problems: list[str] = []
    cur = await conn.execute(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public'"
    )
    actual: dict[str, set[str]] = {}
    for row in await cur.fetchall():
        actual.setdefault(row["table_name"], set()).add(row["column_name"])
    for table, columns in sorted(expected.items()):
        if table not in actual:
            problems.append(f"缺表: {table}")
            continue
        missing = sorted(columns - actual[table])
        if missing:
            problems.append(f"{table} 缺列: {', '.join(missing)}")
    return problems


async def apply(dsn: str, vector_dim: int) -> tuple[list[str], list[str]]:
    """连接目标库并顺序执行全部迁移；返回 (已执行文件名, 对账差异列表)。"""
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
    problems: list[str] = []
    try:
        async with pool.connection() as conn:
            # 跨实例互斥（#110）：CREATE ... IF NOT EXISTS 并非并发安全——两个事务
            # 可同判"不存在"后撞唯一约束；xact 锁覆盖本连接整个隐式事务。
            await conn.execute("SELECT pg_advisory_xact_lock(%s)", (_INIT_LOCK_KEY,))
            for _name, sql in migrations:
                await conn.execute(sql)
            problems = await verify_applied(conn, expected_schema([sql for _, sql in migrations]))
    finally:
        await pool.close()
    return [name for name, _ in migrations], problems


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
            # 池走 pool_factory（row_factory=dict_row）⇒ 行是 dict，必须按列名取
            # （row[0] 下标取法在 dict_row 下必 KeyError，真库 --status 从来跑不通）
            return {row["key"]: row["value"] for row in await cur.fetchall()}
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

    applied, problems = asyncio.run(apply(dsn, vector_dim))
    print(f"已应用 {len(applied)} 个迁移（vector_dim={vector_dim}）：{redact_dsn(dsn)}")
    for name in applied:
        print(f"  ✓ {name}")
    if problems:
        # 对账不齐（典型：存量旧形状库缺列，IF NOT EXISTS 整表跳过）⇒ 非零退出，
        # 把差异打全，不让 "--status 显示成功"掩盖半初始化（#110）。
        print("校验未通过（schema 与迁移声明不一致）：")
        for problem in problems:
            print(f"  ✗ {problem}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
