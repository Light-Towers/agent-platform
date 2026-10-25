"""训练数据摄入服务（A 方案 Stage ③：agent_server/sql 退役后的统一入口 core）。

三个消费方共用本模块，**写入路径只有一份**（否则迁移 CLI 与在线端点必然漂移）：
1. `scripts/migrate_agent_server_sql.py`：批量迁移（读源库三表 → 多 scope 写入 + prune）；
2. `POST /api/meta/ingest`：在线摄入（替代 agent_server 的 `/sql/train`，DDL/文档/范例
   即时进元知识库）；
3. 将来的持续训练/确认提升（confirmed_pairs → 范例库）等写入方。

职责切分：`build_migration_plan` 是纯函数（解析 + 分 scope + 记账）；
`write_scope` 是唯一的写 core（批量重嵌 → upsert，索引游标保序切向量）。
铁律见 migrate_agent_server_sql 模块 docstring：向量一律重算、作用域显式、
宁缺勿错（坏 DDL/未命中文档/空 question 全部记账不静默）。
"""

from __future__ import annotations

from typing import Any

#: 批量向量化的分片大小：一次 embed_texts 的文本数上限（防超长请求/超时）
EMBED_CHUNK = 64


def build_migration_plan(
    ddl_rows: list[dict[str, Any]],
    doc_rows: list[dict[str, Any]],
    example_rows: list[dict[str, Any]],
    *,
    dialect: str = "postgres",
    tenant_override: str | None = None,
    workspace_override: str | None = None,
) -> dict[str, Any]:
    """源三表行 → 按 (tenant, workspace) 分组的迁移计划（纯函数，零 IO）。

    Returns:
        ``{"scopes": [...], "skipped_ddl": [...], "unmapped_docs": [...],
        "skipped_examples": [...]}``
        scope 形如 ``{"tenant_id", "workspace_id", "tables", "examples"}``，
        tables 为 `build_from_tables` 形状（table_comment 已合并 COMMENT ON +
        关联文档），examples 为 `build_from_examples` 形状。

    铁律落地：
    - 文档只关联到**同作用域**的表（跨租户文档串味 = 隔离破裂）；
    - 空 question 的范例记录后跳过（自然键不能是空——upsert 会把它们互相覆盖）；
    - 解析失败的 DDL / 未命中的文档进记账列表，绝不静默。

    override 语义（真库验证抓出的坑）：`None` = 不覆盖（保真源值）；**空串
    `""` = 强制折叠进 '' 作用域**（单租户 legacy 库的标准用法）——若用
    `override or source` 判断，显式空串会被当成"没传"，折叠静默失效。
    """
    from nl2sql_service.ddl_parser import associate_docs_with_tables, parse_ddl

    def _scope(row: dict[str, Any]) -> tuple[str, str]:
        tenant = tenant_override if tenant_override is not None else (row.get("tenant_id") or "")
        workspace = workspace_override if workspace_override is not None else (row.get("workspace_id") or "")
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


async def embed_texts_batched(embedder: Any, texts: list[str], chunk: int = EMBED_CHUNK) -> list[list[float]]:
    """分片批量向量化，保序；embedder 为 None 时返回等长空列表（调用方据此跳过）。

    维度校验由调用方按 `Settings.vector_dim` 做（写入前炸，不写到一半炸）。
    """
    if embedder is None:
        return [[] for _ in texts]
    vectors: list[list[float]] = []
    for start in range(0, len(texts), chunk):
        vectors.extend(await embedder.embed_texts(texts[start : start + chunk]))
    return vectors


async def write_scope(
    meta_repo: Any,
    embedder: Any,
    *,
    tables: list[dict[str, Any]],
    examples: list[dict[str, Any]],
    tenant_id: str,
    workspace_id: str,
    datasource_id: str,
    vector_dim: int,
    tokenizer: str = "bigram",
) -> dict[str, int]:
    """单个作用域的写入 core：批量重嵌 → upsert（迁移 CLI 与 ingest 端点共用）。

    - 向量文本契约与在线召回单源：列 = `{table} {column} {column_comment}`，
      范例 = `question`（SQL 混入只添噪）；
    - 索引游标把扁平向量切回各 table/example——错位 = A 租户向量挂 B 租户
      范例（静默串味比报错更糟）；
    - 维度不符在建库前炸（带处置说明），不写半截坏数据。
    """
    from nl2sql_service.services.meta_knowledge_service import MetaKnowledgeService

    column_texts = [
        f"{t['table_name']} {c['column_name']} {c.get('column_comment', '')}"
        for t in tables
        for c in t["columns"]
    ]
    example_texts = [e["question"] for e in examples]
    column_vectors = await embed_texts_batched(embedder, column_texts)
    example_vectors = await embed_texts_batched(embedder, example_texts)
    for vectors in (column_vectors, example_vectors):
        for vector in vectors:
            if vector and len(vector) != vector_dim:
                raise ValueError(
                    f"embedding 维度 {len(vector)} 与 Settings.vector_dim={vector_dim} 不一致；"
                    "换模型必须同步 VECTOR_DIM 并全量重灌（001/004 DDL 的 vector 列维度）"
                )

    service = MetaKnowledgeService(
        meta_repo=meta_repo,
        embedder=None,  # 预嵌模式：向量已在上面批量算好（逐条 embed = N 次 API 调用）
        tokenizer=tokenizer,
        vector_dim=vector_dim,
        datasource_id=datasource_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    col_idx = 0
    ex_idx = 0
    embedded_tables = []
    for table in tables:
        columns = []
        for column in table["columns"]:
            columns.append({**column, "embedding": column_vectors[col_idx]})
            col_idx += 1
        embedded_tables.append({**table, "columns": columns})
    embedded_examples = []
    for example in examples:
        embedded_examples.append({**example, "embedding": example_vectors[ex_idx]})
        ex_idx += 1
    return {
        "columns": await service.build_from_tables(embedded_tables),
        "examples": await service.build_from_examples(embedded_examples),
    }
