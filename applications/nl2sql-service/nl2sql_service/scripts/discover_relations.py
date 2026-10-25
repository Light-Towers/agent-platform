"""关系种子发现（§5.14-R4）：从源库物理声明派生关系声明，写进 meta 库。

三档种子（R4）：
- **T1 全自动零人工**：FK 约束（`information_schema` 的
  `table_constraints`/`key_column_usage`/`constraint_column_usage`，
  PG/MySQL 同视图）——物理声明即设计意图，照单全收；
- **T2 机器提名人工确认**：跨表同名列，且其中一侧是 PK/UK 时附基数暗示
  （many_to_one 候选）。**默认不写入**（`--include-t2` 才写）——机器只能
  提名，`exhibitor_id` 类同名不同义在数仓是现实，人不确认不进 live 集；
- T3 纯人工声明：YAML 的 `relations` 段（build_meta_knowledge --config），
  不经本脚本。

用法：
    python -m nl2sql_service.scripts.discover_relations \
        --meta-dsn "$META_DB_DSN" --dw-dsn "$DW_DB_DSN" [--schema public] \
        [--datasource ds-1] [--include-t2] [--dry-run] [--json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

#: FK 约束（T1）：PG/MySQL 通用的 information_schema 三角连接
_FK_SQL = (
    "SELECT tc.table_name AS left_table, kcu.column_name AS left_column, "
    "ccu.table_name AS right_table, ccu.column_name AS right_column "
    "FROM information_schema.table_constraints tc "
    "JOIN information_schema.key_column_usage kcu "
    "  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema "
    "JOIN information_schema.constraint_column_usage ccu "
    "  ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema "
    "WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = %s"
)
#: PK/UK 列（T2 的基数暗示依据）
_KEY_SQL = (
    "SELECT kcu.table_name, kcu.column_name, tc.constraint_type "
    "FROM information_schema.table_constraints tc "
    "JOIN information_schema.key_column_usage kcu "
    "  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema "
    "WHERE tc.constraint_type IN ('PRIMARY KEY', 'UNIQUE') AND tc.table_schema = %s"
)
#: 跨表同名列（T2 提名池）
_SAME_NAME_SQL = (
    "SELECT column_name, array_agg(DISTINCT table_name) AS tables "
    "FROM information_schema.columns "
    "WHERE table_schema = %s "
    "GROUP BY column_name HAVING count(DISTINCT table_name) > 1 "
    "ORDER BY column_name"
)


def discover_fk_relations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """T1：FK → 关系声明（many_to_one：多方指向唯一方）。"""
    return [
        {
            "left_table": r["left_table"],
            "left_column": r["left_column"],
            "right_table": r["right_table"],
            "right_column": r["right_column"],
            "relation_type": "many_to_one",
            "note": "源库外键约束（T1 自动发现）",
        }
        for r in rows
    ]


def discover_same_name_candidates(
    same_name_rows: list[dict[str, Any]], key_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """T2：同名列且一侧有 PK/UK → many_to_one 候选提名（待人工确认）。"""
    key_cols = {(r["table_name"], r["column_name"]) for r in key_rows}
    candidates: list[dict[str, Any]] = []
    for row in same_name_rows:
        tables = list(row.get("tables") or [])
        if len(tables) < 2:
            continue
        key_side = [t for t in tables if (t, row["column_name"]) in key_cols]
        if not key_side:
            continue  # 两侧都无唯一约束：同名也未必可连，不提名
        for other in tables:
            if other == key_side[0]:
                continue
            candidates.append(
                {
                    "left_table": other,
                    "left_column": row["column_name"],
                    "right_table": key_side[0],
                    "right_column": row["column_name"],
                    "relation_type": "many_to_one",
                    "note": "同名列 + 右表唯一约束（T2 机提候选，待人工确认）",
                }
            )
    return candidates


async def main_async(args: argparse.Namespace) -> tuple[int, dict]:
    from nl2sql_service.clients.postgres_client_manager import PostgresClientManager, redact_dsn
    from nl2sql_service.conf.settings import get_settings
    from nl2sql_service.repositories.postgres.dw.dw_repository import DwRepository
    from nl2sql_service.repositories.postgres.meta.meta_repository import MetaRepository
    from nl2sql_service.services.meta_knowledge_service import MetaKnowledgeService

    settings = get_settings()
    dw_pg = PostgresClientManager(args.dw_dsn, name="dw-discover", statement_timeout_ms=settings.dw_db_statement_timeout_ms)
    await dw_pg.connect()
    try:
        dw = DwRepository(pool=dw_pg.pool)
        fk_rows = await dw.execute_readonly(_FK_SQL, (args.schema,))
        relations = discover_fk_relations(fk_rows)
        if args.include_t2:
            key_rows = await dw.execute_readonly(_KEY_SQL, (args.schema,))
            same_name_rows = await dw.execute_readonly(_SAME_NAME_SQL, (args.schema,))
            relations.extend(discover_same_name_candidates(same_name_rows, key_rows))
    finally:
        await dw_pg.close()

    payload: dict[str, Any] = {
        "relations": relations,
        "fk_count": len(discover_fk_relations(fk_rows)),
        "t2_count": len(relations) - len(discover_fk_relations(fk_rows)),
        "dw_dsn": redact_dsn(args.dw_dsn),
    }

    if args.dry_run:
        return 0, payload

    meta_pg = PostgresClientManager(
        args.meta_dsn, name="meta-discover", statement_timeout_ms=settings.meta_db_statement_timeout_ms
    )
    await meta_pg.connect()
    try:
        service = MetaKnowledgeService(
            meta_repo=MetaRepository(pool=meta_pg.pool, table_prefix=settings.table_prefix),
            embedder=None,  # 关系/别名无向量（001 DDL 本就没有该列）
            tokenizer=settings.tokenizer,
            vector_dim=settings.vector_dim,
        )
        stats = await service.build_from_relations(relations)
        payload["written"] = stats
    finally:
        await meta_pg.close()
    return 0, payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从源库物理声明发现关系种子（R4-T1/T2）")
    parser.add_argument("--meta-dsn", required=True, help="元知识库 DSN")
    parser.add_argument("--dw-dsn", required=True, help="业务数仓 DSN（只读探测）")
    parser.add_argument("--schema", default="public")
    parser.add_argument("--datasource", default="", help="datasource_id 作用域（P1-6；缺省空）")
    parser.add_argument("--include-t2", action="store_true", help="纳入同名列机提候选（默认只写 T1 外键）")
    parser.add_argument("--dry-run", action="store_true", help="只发现不写库")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    _code, payload = asyncio.run(main_async(args))
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            f"关系种子发现（dw={payload['dw_dsn']}）：外键 {payload['fk_count']} 条"
            + (f" + 同名列候选 {payload['t2_count']} 条" if args.include_t2 else "（T2 未启用）")
        )
        for rel in payload["relations"]:
            print(f"  - {rel['left_table']}.{rel['left_column']} → {rel['right_table']}.{rel['right_column']} [{rel['note']}]")
        if "written" in payload:
            print(f"  已写入 meta 库: {payload['written']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
