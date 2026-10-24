#!/usr/bin/env python3
"""真 PG 往返实取：nl2sql 元知识迁移链 + 作用域写入路径 + 发布顺序约束。

来历：分支 `feat/nl2sql-ttl-and-006-slim` 的 B-1/B-2/B-3 三个阻塞项在单测全绿下存活
（见 `docs/plans/plan-platform-tenant-workspace-identity-2026-10-18.md` §9.16）。
本脚本把当时的 11 项断言固化成**任何改到 nl2sql 迁移或 `_upsert`/`_stamp` 后必须重跑**
的判据：读数应当逐项 PASS，任一项翻红就是回归。

为什么能零基建跑：`pgserver` 的 wheel 自带 PostgreSQL 16.2 **且内置 pgvector**
（免 docker/免管理员），配 `WindowsSelectorEventLoopPolicy` 后 psycopg 异步可用。
配方与四条坑见 `docs/operations/testing-playbook.md` §3.4。

退出码：`0` = 全部断言通过 · `1` = 有断言未过（回归） · `2` = 前置不可用
（pgserver 缺席 / PG 起不来）——`2` **从不**折算成通过。

    uv run --no-sync --with pgserver python scripts/evidence/nl2sql_real_pg_probe.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PGDATA = ROOT / ".pgserver-probe"  # 被根 .gitignore 的 `.*/` 天然忽略
DB = "nl2sql_evidence"
VECTOR_DIM = 4

try:
    import pgserver
    import psycopg
except ImportError as exc:  # 前置不可用 ≠ 通过
    print(f"[PRE] 依赖不可用（需 --with pgserver）: {exc}")
    sys.exit(2)

sys.path.insert(0, str(ROOT / "applications" / "nl2sql-service"))

FAILS: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILS.append(label)


async def phase_migrations(db: str) -> None:
    """B-1 的正面判据：生产入口能建全链，且第二遍零差异（幂等）。"""
    from nl2sql_service.scripts.init_meta_schema import apply

    print("=== 1. init_meta_schema.apply 全链 001-006（生产入口，非手拼 SQL）===")
    names, problems = await apply(db, vector_dim=VECTOR_DIM)
    check(f"{len(names) or '?'} 份迁移全部应用（期望 6）", len(names) == 6, str(names))
    check("对账零差异", not problems, str(problems))

    print("=== 2. 幂等第二遍（同库重跑）===")
    names2, problems2 = await apply(db, vector_dim=VECTOR_DIM)
    check("重跑不报错且仍零差异", len(names2) == 6 and not problems2, str(problems2))


async def phase_writes(db: str) -> None:
    """B-2 的正面判据 + D8 摘键语义反证。"""
    from agent_runtime.pool_factory import create_pool
    from nl2sql_service.repositories.postgres.meta.meta_repository import MetaRepository
    from nl2sql_service.services.meta_knowledge_service import MetaKnowledgeService

    vec = [0.1, 0.2, 0.3, 0.4]
    pool = create_pool(dsn=db, name="evidence", min_size=1, max_size=2, timeout=10.0, read_only=False)
    await pool.open()
    try:
        print("=== 3. workspace_id='' 默认写入路径（曾 23502）===")
        svc = MetaKnowledgeService(
            meta_repo=MetaRepository(pool), datasource_id="ds1", tenant_id="t1", workspace_id="", vector_dim=VECTOR_DIM
        )
        stats = await svc.build_from_tables(
            [
                {
                    "table_name": "venues",
                    "table_comment": "场馆",
                    "columns": [
                        {
                            "column_name": "id",
                            "column_comment": "主键",
                            "data_type": "int",
                            "embedding": vec,
                        }
                    ],
                }
            ]
        )
        check("列行写入成功", stats["inserted"] == 1, str(stats))

        print("=== 4. 绕过 _stamp 的直接仓储写入（discover_relations 形态：三个作用域参数都不传）===")
        ok = await MetaRepository(pool).save_relation(
            {
                "left_table": "orders",
                "left_column": "venue_id",
                "right_table": "venues",
                "right_column": "id",
                "relation_type": "many_to_one",
                "note": "",
                "tenant_id": "t1",
                "datasource_id": "ds1",
            }
        )
        check("关系行写入成功（data 里无 workspace_id 键）", ok is True, f"inserted={ok}")

        print("=== 5. D8 反证：跨空间同问法 ⇒ 合并为一行、首灌来源不被覆盖 ===")
        svc_a = MetaKnowledgeService(
            meta_repo=MetaRepository(pool), datasource_id="ds1", tenant_id="t1", workspace_id="w-a", vector_dim=VECTOR_DIM
        )
        svc_b = MetaKnowledgeService(
            meta_repo=MetaRepository(pool), datasource_id="ds1", tenant_id="t1", workspace_id="w-b", vector_dim=VECTOR_DIM
        )
        await svc_a.build_from_examples([{"question": "场馆有多少？", "sql": "SELECT count(*) FROM venues", "embedding": vec}])
        s_b = await svc_b.build_from_examples([{"question": "场馆有多少？", "sql": "SELECT count(1) FROM venues", "embedding": vec}])
        check("第二次是更新而非新插", s_b["inserted"] == 0 and s_b["updated"] == 1, str(s_b))
    finally:
        await pool.close()

    with psycopg.connect(db) as c:
        rows = c.execute("select workspace_id, count(*) from nl2sql_column_info group by 1").fetchall()
        check("作用域列落 '' 而非 NULL", rows == [("", 1)], str(rows))
        ex = c.execute("select workspace_id, sql from nl2sql_example_info").fetchall()
        check("范例仅一行且首灌来源保留 w-a", ex == [("w-a", "SELECT count(1) FROM venues")], str(ex))
        key = c.execute(
            "select string_agg(a.attname, ',' order by a.attname) from pg_constraint c "
            "join pg_class r on r.oid=c.conrelid join pg_attribute a on a.attrelid=r.oid and a.attnum=any(c.conkey) "
            "where r.relname='nl2sql_example_info' and c.contype='u'"
        ).fetchone()[0]
        check("006 摘键后的唯一键 = (datasource_id,question,tenant_id)", key == "datasource_id,question,tenant_id", str(key))


async def phase_release_order(db: str) -> None:
    """B-3 判据：未应用 006 的库上跑当前代码**必须** 42P10（不是被代码绕过）。"""
    from agent_runtime.pool_factory import create_pool
    from nl2sql_service.repositories.postgres.meta.meta_repository import MetaRepository
    from nl2sql_service.scripts.init_meta_schema import load_migrations

    print("=== 6. 库停在 005（未应用 006）时当前代码写入 ===")
    with psycopg.connect(db, autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE")
        c.execute("CREATE SCHEMA public")
        for name, sql in load_migrations(vector_dim=VECTOR_DIM):
            if name.startswith(("001_", "002_", "003_", "004_", "005_")):
                c.execute(sql)
    pool = create_pool(dsn=db, name="b3", min_size=1, max_size=2, timeout=10.0, read_only=False)
    await pool.open()
    try:
        await MetaRepository(pool).save_example(
            {
                "question": "q",
                "sql": "s",
                "source": "human",
                "embedding": [0.1, 0.2, 0.3, 0.4],
                "tenant_id": "t1",
                "datasource_id": "ds1",
                "workspace_id": "",
            }
        )
        check("未迁移库上写入必须失败", False, "意外成功 ⇒ 发布顺序约束被绕过，须查为何")
    except psycopg.Error as e:
        check(
            "未迁移库 ⇒ 42P10（先迁移后发代码可核对）",
            type(e).__name__ == "InvalidColumnReference",
            str(e).splitlines()[0][:90],
        )
    finally:
        await pool.close()


def main() -> int:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        srv = pgserver.get_server(str(PGDATA))
        base = srv.get_uri()
        with psycopg.connect(base, autocommit=True) as c:
            c.execute(f"DROP DATABASE IF EXISTS {DB}")
            c.execute(f"CREATE DATABASE {DB}")
    except Exception as exc:  # noqa: BLE001 — 前置不可用的归因必须覆盖任意异常形状
        # pgserver 起库失败可能是 RuntimeError/OSError/psycopg.OperationalError，收窄成
        # 具体类型会让某一种失败变成 traceback 而不是 rc=2；异常类型名照打进文案供归因。
        print(f"[PRE] 本机 PG 起不来/连不上 [{type(exc).__name__}]: {exc}")
        return 2
    db = base.rsplit("/", 1)[0] + f"/{DB}"
    asyncio.run(phase_migrations(db))
    asyncio.run(phase_writes(db))
    asyncio.run(phase_release_order(db))
    print("\n结论:", "全部通过" if not FAILS else f"{len(FAILS)} 项未过: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
