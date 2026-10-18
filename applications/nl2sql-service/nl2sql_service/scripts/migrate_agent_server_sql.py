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
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

#: 批量向量化的分片大小：一次 embed_texts 的文本数上限（防超长请求/超时）
_EMBED_CHUNK = 64


def build_migration_plan(
    ddl_rows: list[dict[str, Any]],
    doc_rows: list[dict[str, Any]],
    example_rows: list[dict[str, Any]],
    *,
    dialect: str = "postgres",
    tenant_override: str = "",
    workspace_override: str = "",
) -> dict[str, Any]:
    """源三表行 → 按 (tenant, workspace) 分组的迁移计划（纯函数，零 IO）。

    Returns:
        ``{"scopes": [...], "skipped_ddl": [...], "unmapped_docs": [...]}``
        scope 形如 ``{"tenant_id", "workspace_id", "tables", "examples"}``，
        tables 为 `build_from_tables` 形状（table_comment 已合并 COMMENT ON +
        关联文档），examples 为 `build_from_examples` 形状。

    铁律落地：
    - 文档只关联到**同作用域**的表（跨租户文档串味 = 隔离破裂）；
    - 空 question 的范例记录后跳过（自然键不能是空——upsert 会把它们互相覆盖）；
    - 解析失败的 DDL / 未命中的文档进两个记账列表，绝不静默。
    """
    from nl2sql_service.ddl_parser import associate_docs_with_tables, parse_ddl

    def _scope(row: dict[str, Any]) -> tuple[str, str]:
        tenant = tenant_override or row.get("tenant_id") or ""
        workspace = workspace_override or row.get("workspace_id") or ""
        return tenant, workspace

    # ① DDL → 每作用域的表集合（先解析全部，文档关联需要表名清单）
    tables_by_scope: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    skipped_ddl: list[str] = []
    for row in ddl_rows:
        tenant, workspace = _scope(row)
        content = row.get("content") or ""
        tables, skipped = parse_ddl(content, dialect)
        scope_tables = tables_by_scope.setdefault((tenant, workspace), {})
        for table in tables:
            if table["table_name"] in scope_tables:
                skipped_ddl.append(f"[{tenant}/{workspace}] duplicate CREATE TABLE {table['table_name']}（保留首见）")
                continue
            scope_tables[table["table_name"]] = table
        for item in skipped:
            skipped_ddl.append(f"[{tenant}/{workspace}] {item}")

    # ② 文档 → 同作用域表的 table_comment（合并进 COMMENT ON 之后）
    docs_by_scope: dict[tuple[str, str], list[str]] = {}
    for row in doc_rows:
        tenant, workspace = _scope(row)
        docs_by_scope.setdefault((tenant, workspace), []).append(row.get("content") or "")

    unmapped_docs: list[str] = []
    for scope, docs in docs_by_scope.items():
        table_names = list(tables_by_scope.get(scope, {}))
        by_table, unmapped = associate_docs_with_tables(docs, table_names)
        for name, texts in by_table.items():
            table = tables_by_scope[scope][name]
            base = table.get("table_comment", "")
            extra = [t for t in texts if t.strip()]
            table["table_comment"] = "\n\n".join([base, *extra]) if base else "\n\n".join(extra)
        for text in unmapped:
            unmapped_docs.append(f"[{scope[0]}/{scope[1]}] {text[:80]}")

    # ③ 范例 → 每作用域（空 question 记账跳过）
    examples_by_scope: dict[tuple[str, str], list[dict[str, Any]]] = {}
    skipped_examples: list[str] = []
    for row in example_rows:
        tenant, workspace = _scope(row)
        question = (row.get("question") or "").strip()
        if not question:
            skipped_examples.append(f"[{tenant}/{workspace}] empty question（sql={row.get('sql', '')[:40]!r}）")
            continue
        examples_by_scope.setdefault((tenant, workspace), []).append(
            {"question": question, "sql": row.get("sql") or "", "source": "human"}
        )

    scopes = [
        {
            "tenant_id": tenant,
            "workspace_id": workspace,
            "tables": list(tables_by_scope.get((tenant, workspace), {}).values()),
            "examples": examples_by_scope.get((tenant, workspace), []),
        }
        for tenant, workspace in sorted({*tables_by_scope, *examples_by_scope})
    ]
    return {
        "scopes": scopes,
        "skipped_ddl": skipped_ddl,
        "unmapped_docs": unmapped_docs,
        "skipped_examples": skipped_examples,
    }


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


async def _embed_batched(embedder: Any, texts: list[str], chunk: int = _EMBED_CHUNK) -> list[list[float]]:
    """分片批量向量化，保序；embedder 为 None 时返回等长空列表（调用方据此跳过）。

    维度校验与 `_embed` 同标准：不等直接抛——迁移跑到一半才炸会更难收场。
    """
    if embedder is None:
        return [[] for _ in texts]
    vectors: list[list[float]] = []
    for start in range(0, len(texts), chunk):
        vectors.extend(await embedder.embed_texts(texts[start : start + chunk]))
    return vectors


async def main_async(
    source_dsn: str,
    dsn: str,
    *,
    datasource: str = "",
    tenant: str = "",
    workspace: str = "",
    prune: bool = False,
    dry_run: bool = False,
    dialect: str = "postgres",
) -> dict[str, Any]:
    """迁移主流程：读源 → 计划 →（批量重嵌 → 按 scope upsert）→ 报告。"""
    from nl2sql_service.clients.embedding_client_manager import build_embedder
    from nl2sql_service.clients.postgres_client_manager import PostgresClientManager, redact_dsn
    from nl2sql_service.conf.settings import get_settings
    from nl2sql_service.repositories.postgres.meta.meta_repository import MetaRepository
    from nl2sql_service.services.meta_knowledge_service import MetaKnowledgeService

    settings = get_settings()
    ds_id = datasource or settings.datasource_id

    source = PostgresClientManager(source_dsn, name="migration-source", statement_timeout_ms=60_000)
    await source.connect()
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

        # 批量重嵌（铁律 1：只取文本，向量用目标侧 embedder 重算）
        embedder = build_embedder(
            settings.embedding_backend,
            api_key=settings.embedding_api_key,
            model=settings.embedding_model,
            base_url=settings.embedding_base_url,
        )
        column_texts = [
            f"{t['table_name']} {c['column_name']} {c.get('column_comment', '')}"
            for s in plan["scopes"]
            for t in s["tables"]
            for c in t["columns"]
        ]
        example_texts = [e["question"] for s in plan["scopes"] for e in s["examples"]]
        column_vectors = await _embed_batched(embedder, column_texts)
        example_vectors = await _embed_batched(embedder, example_texts)
        dim = settings.vector_dim
        for vectors in (column_vectors, example_vectors):
            for vector in vectors:
                if vector and len(vector) != dim:
                    raise ValueError(
                        f"embedding 维度 {len(vector)} 与 Settings.vector_dim={dim} 不一致；"
                        "换模型必须同步 VECTOR_DIM 并全量重灌（004 DDL 的 vector 列维度）"
                    )

        # 向量按 plan["scopes"] 展平序建、再按同一顺序切回各 scope——
        # 索引游标保序对应，错位 = A 租户向量挂 B 租户范例（静默串味比报错更糟）
        meta_repo = MetaRepository(pool=target.pool, table_prefix=settings.table_prefix)
        col_idx = 0
        ex_idx = 0
        for scope in plan["scopes"]:
            # 每个 scope 一个 service 实例：_stamp 把作用域盖进每一行
            service = MetaKnowledgeService(
                meta_repo=meta_repo,
                embedder=None,  # 预嵌模式：向量已在上面批量算好
                tokenizer=settings.tokenizer,
                vector_dim=dim,
                datasource_id=ds_id,
                tenant_id=scope["tenant_id"],
                workspace_id=scope["workspace_id"],
            )
            tables = []
            for table in scope["tables"]:
                columns = []
                for column in table["columns"]:
                    columns.append({**column, "embedding": column_vectors[col_idx]})
                    col_idx += 1
                tables.append({**table, "columns": columns})
            examples = []
            for example in scope["examples"]:
                examples.append({**example, "embedding": example_vectors[ex_idx]})
                ex_idx += 1
            stats = {
                "columns": await service.build_from_tables(tables),
                "examples": await service.build_from_examples(examples),
            }
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
    parser.add_argument("--tenant", default="", help="覆盖所有源行的 tenant_id（单租户 legacy 库折叠用；缺省保真源值）")
    parser.add_argument("--workspace", default="", help="覆盖所有源行的 workspace_id（缺省保真源值）")
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
