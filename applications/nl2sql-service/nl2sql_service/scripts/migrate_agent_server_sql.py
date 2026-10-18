"""迁移 agent_server/sql 训练三件套 → nl2sql 元知识库（A 方案 Stage ② 执行入口）。

用法：
    python -m nl2sql_service.scripts.migrate_agent_server_sql \\
        --source-dsn "$AGENT_SERVER_DB_DSN" --dsn "$META_DB_DSN" \\
        [--datasource dw] [--tenant T] [--workspace W] [--prune] [--dry-run]

映射（方案 A ②）：
    sql_ddl.content  → nl2sql_column_info（parse_ddl：表/列/类型/COMMENT ON 注释）
    sql_docs.content → 同作用域表的 table_comment（associate_docs_with_tables；
                       未命中表名的文档进 unmapped 记账——静默丢 = 丢业务口径）
    sql_examples     → nl2sql_example_info（question 自然键 upsert，004）

铁律（每条都对应一个真实故障模式）：
1. **向量一律重算**：源 embedding 是 agent_server 的嵌入模型算的，与目标侧
   `Settings.embedding_*` 可能不同模型/维度——拷贝向量 = 维度不符炸库，或维度
   相同但语义错位静默劣化。本脚本只取文本。
2. **作用域保真**：源行 (tenant_id, workspace_id) 原样带到目标；--tenant/
   --workspace 是**覆盖**（单租户 legacy 库折叠用）。注意源默认 tenant='default'
   （006 迁移）≠ nl2sql 默认 ''——不覆盖且源是 legacy 单租户，在线召回按 ''
   过滤永远召不到迁移行（报告会打出每个 scope 的实际落点）。
3. **prune 只删范例**：列有两个写入源（MetricConfig 构建 + 本迁移），迁移删列
   会把配置构建的行误删；范例只有迁移一个源，可安全差异删。
4. 幂等：重跑 = upsert 更新（同 question 后来者胜），不翻倍。

架构（Stage ③ 起）：解析/分 scope/写入 core 已上移为共享件
`nl2sql_service.services.ingest_service`——在线摄入端点 `POST /api/meta/ingest`
（替代 agent_server `/sql/train`）与 CLI 共用同一份写入路径，避免两路漂移。
本模块只保留：源库读取、多 scope 循环、prune、CLI 与报告。
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

#: 兼容既有导入路径（测试按脚本模块导入这两个名字）；实现已上移 ingest_service
from nl2sql_service.services.ingest_service import (  # noqa: F401 — re-export
    build_migration_plan,
    embed_texts_batched,
    write_scope,
)

#: 兼容旧名（早前测试用 `_embed_batched`）
_embed_batched = embed_texts_batched


async def _read_source(pool: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """读源库三表（缺表 = agent_server 基线/006 未应用，fail-fast 不静默）。"""
    queries = {
        "ddl": "SELECT tenant_id, workspace_id, content FROM sql_ddl ORDER BY id",
        "docs": "SELECT tenant_id, workspace_id, content FROM sql_docs ORDER BY id",
        "examples": "SELECT tenant_id, workspace_id, question, sql FROM sql_examples ORDER BY id",
    }
    rows: dict[str, list[dict[str, Any]]] = {}
    try:
        for name, sql in queries.items():
            async with pool.connection() as conn:
                cur = await conn.execute(sql)
                fetched = await cur.fetchall()
            rows[name] = [dict(r) for r in fetched]
    except Exception as exc:  # noqa: BLE001 - 统一转译成"缺表/连不上"的可操作错误
        if "does not exist" in str(exc) or "UndefinedTable" in type(exc).__name__:
            raise RuntimeError(
                f"源库缺 sql_ddl/sql_docs/sql_examples 表（{exc}）。"
                "确认 --source-dsn 指向应用过 agent_runtime 基线 + 006 的 agent_server 库。"
            ) from exc
        raise
    return rows["ddl"], rows["docs"], rows["examples"]


async def main_async(
    source_dsn: str,
    dsn: str,
    *,
    datasource: str = "",
    tenant: str | None = None,
    workspace: str | None = None,
    prune: bool = False,
    dry_run: bool = False,
    dialect: str = "postgres",
) -> dict[str, Any]:
    """迁移主流程：读源 → 计划 →（按 scope 写 core）→ 报告。"""
    from nl2sql_service.clients.embedding_client_manager import build_embedder
    from nl2sql_service.clients.postgres_client_manager import PostgresClientManager, redact_dsn
    from nl2sql_service.conf.settings import get_settings
    from nl2sql_service.repositories.postgres.meta.meta_repository import MetaRepository

    settings = get_settings()
    ds_id = datasource or settings.datasource_id

    source = PostgresClientManager(source_dsn, name="migration-source", statement_timeout_ms=60_000)
    await source.connect()
    if not dry_run:
        target = PostgresClientManager(
            dsn,
            name="migration-target",
            min_size=settings.meta_db_pool_min_size,
            max_size=settings.meta_db_pool_max_size,
            timeout=settings.meta_db_pool_timeout,
            statement_timeout_ms=settings.meta_db_statement_timeout_ms,
        )
        await target.connect()
    try:
        ddl_rows, doc_rows, example_rows = await _read_source(source.pool)
        plan = build_migration_plan(
            ddl_rows,
            doc_rows,
            example_rows,
            dialect=dialect,
            tenant_override=tenant,
            workspace_override=workspace,
        )
        report: dict[str, Any] = {
            "source": redact_dsn(source_dsn),
            "target": redact_dsn(dsn),
            "dry_run": dry_run,
            "source_rows": {"ddl": len(ddl_rows), "docs": len(doc_rows), "examples": len(example_rows)},
            "scopes": [],
            "skipped_ddl": plan["skipped_ddl"],
            "unmapped_docs": plan["unmapped_docs"],
            "skipped_examples": plan["skipped_examples"],
        }
        if dry_run:
            report["scopes"] = [
                {
                    "tenant_id": s["tenant_id"],
                    "workspace_id": s["workspace_id"],
                    "tables": len(s["tables"]),
                    "columns": sum(len(t["columns"]) for t in s["tables"]),
                    "examples": len(s["examples"]),
                }
                for s in plan["scopes"]
            ]
            return report

        embedder = build_embedder(
            settings.embedding_backend,
            api_key=settings.embedding_api_key,
            model=settings.embedding_model,
            base_url=settings.embedding_base_url,
        )
        meta_repo = MetaRepository(pool=target.pool, table_prefix=settings.table_prefix)
        for scope in plan["scopes"]:
            stats = await write_scope(
                meta_repo,
                embedder,
                tables=scope["tables"],
                examples=scope["examples"],
                tenant_id=scope["tenant_id"],
                workspace_id=scope["workspace_id"],
                datasource_id=ds_id,
                vector_dim=settings.vector_dim,
                tokenizer=settings.tokenizer,
            )
            if prune:
                # 铁律 3：范例只有一个写入源（本迁移），可安全差异删；列不删（双写入源）
                stats["examples_pruned"] = await meta_repo.prune_examples(
                    {e["question"] for e in scope["examples"]},
                    scope["tenant_id"],
                    scope["workspace_id"],
                    ds_id,
                )
            report["scopes"].append({"tenant_id": scope["tenant_id"], "workspace_id": scope["workspace_id"], **stats})
        return report
    finally:
        await source.close()
        if not dry_run:
            await target.close()


def _print_report(report: dict[str, Any]) -> None:
    print(f"迁移报告（{report['source']} → {report['target']}）：")
    print(f"  源行数：{report['source_rows']}")
    for scope in report["scopes"]:
        if report["dry_run"]:
            print(
                f"  scope [{scope['tenant_id']}/{scope['workspace_id']}]: "
                f"tables={scope['tables']} columns={scope['columns']} examples={scope['examples']}（dry-run 未写入）"
            )
            continue
        columns = scope["columns"]
        examples = scope["examples"]
        line = (
            f"  scope [{scope['tenant_id']}/{scope['workspace_id']}]: "
            f"columns inserted={columns.get('inserted', 0)} updated={columns.get('updated', 0)}; "
            f"examples inserted={examples.get('inserted', 0)} updated={examples.get('updated', 0)}"
        )
        if "examples_pruned" in scope:
            line += f"; examples pruned={scope['examples_pruned']}"
        print(line)
    for label in ("skipped_ddl", "unmapped_docs", "skipped_examples"):
        items = report.get(label) or []
        if items:
            print(f"  {label}: {len(items)} 条（前 5 条）：")
            for item in items[:5]:
                print(f"    - {item}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="迁移 agent_server/sql 训练三件套 → nl2sql 元知识库（A 方案 Stage ②）")
    parser.add_argument("--source-dsn", required=True, help="agent_server 源库 DSN（sql_ddl/sql_docs/sql_examples 所在）")
    parser.add_argument("--dsn", required=True, help="nl2sql 元知识库 DSN")
    parser.add_argument("--datasource", default="", help="datasource_id 作用域（缺省取 Settings.datasource_id）")
    parser.add_argument("--tenant", default=None, help="覆盖所有源行的 tenant_id（单租户 legacy 库折叠用；显式传 '' 折叠进空作用域；缺省保真源值）")
    parser.add_argument("--workspace", default=None, help="覆盖所有源行的 workspace_id（语义同 --tenant）")
    parser.add_argument("--prune", action="store_true", help="差异删范例（源里已不存在的 question）；列不删（双写入源）")
    parser.add_argument("--dry-run", action="store_true", help="只解析与报告，不连目标库写入、不算向量")
    parser.add_argument("--dialect", default="postgres", help="DDL 解析方言（sqlglot read；缺省 postgres）")
    args = parser.parse_args(argv)
    report = asyncio.run(
        main_async(
            args.source_dsn,
            args.dsn,
            datasource=args.datasource,
            tenant=args.tenant,
            workspace=args.workspace,
            prune=args.prune,
            dry_run=args.dry_run,
            dialect=args.dialect,
        )
    )
    _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
