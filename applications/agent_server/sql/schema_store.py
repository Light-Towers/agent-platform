"""训练三件套存储：DDL / 业务文档 / (问题, SQL) 范例（Vanna 式持续训练）。

借鉴 Vanna 的核心机制：准确率来自"训练数据三件套 + 检索注入"，而非模型临场发挥。
不依赖已归档的 vanna 包，训练数据统一存 pgvector，按语义相似度召回。

隔离契约（ADR-0006 T9/W1）：sql_* 三表以 ``tenant_id`` 为安全边界、
``workspace_id`` 为归属维；召回不再接受「空 workspace = 全库检索」旁路，
读写均成对带 tenant 谓词（tenant 漏传 fail-fast，同 _tenant_gate 语义）。
"""

from agent_core.memory._tenant_gate import _TENANT_UNSET, resolve_tenant
from agent_runtime.db import vector_search

from agent_server.rag.embed import embed_query, embed_texts


async def store_ddl(
    pool, ddl: str, workspace_id: str = "", *, tenant_id: str = _TENANT_UNSET,
) -> None:
    tenant_id = resolve_tenant(tenant_id)
    vec = (await embed_texts([ddl]))[0]
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO sql_ddl (tenant_id, content, embedding, workspace_id) VALUES (%s, %s, %s, %s)",
            (tenant_id, ddl, vec, workspace_id),
        )


async def store_doc(
    pool, doc: str, workspace_id: str = "", *, tenant_id: str = _TENANT_UNSET,
) -> None:
    tenant_id = resolve_tenant(tenant_id)
    vec = (await embed_texts([doc]))[0]
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO sql_docs (tenant_id, content, embedding, workspace_id) VALUES (%s, %s, %s, %s)",
            (tenant_id, doc, vec, workspace_id),
        )


async def store_example(
    pool, question: str, sql: str, workspace_id: str = "", *, tenant_id: str = _TENANT_UNSET,
) -> None:
    tenant_id = resolve_tenant(tenant_id)
    vec = (await embed_texts([question]))[0]
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO sql_examples (tenant_id, question, sql, embedding, workspace_id) "
            "VALUES (%s, %s, %s, %s, %s)",
            (tenant_id, question, sql, vec, workspace_id),
        )


async def fetch_context(
    pool, question: str, k: int = 3, workspace_id: str = "", *, tenant_id: str = _TENANT_UNSET,
) -> dict:
    """按语义相似度召回最相关的 DDL / 文档 / 范例（租户谓词必经）。

    旧实现 ``workspace_id`` 为空时不加任何谓词（全库召回）——多租户下即
    跨租户语料泄漏通道（ADR-0006 W1）；现 tenant 谓词无条件拼入，
    workspace 仅作同租户内的归属细化。
    """
    if pool is None:
        return {"ddl": [], "docs": [], "examples": []}
    tenant_id = resolve_tenant(tenant_id)
    embedding = await embed_query(question)

    async def _top(table: str, cols: str) -> list:
        if workspace_id:
            return await vector_search(
                pool, table, cols, embedding, k=k,
                where="embedding IS NOT NULL AND tenant_id = %s AND workspace_id = %s",
                where_params=(tenant_id, workspace_id),
            )
        return await vector_search(
            pool, table, cols, embedding, k=k,
            where="embedding IS NOT NULL AND tenant_id = %s",
            where_params=(tenant_id,),
        )

    ddl_rows = await _top("sql_ddl", "content")
    doc_rows = await _top("sql_docs", "content")
    example_rows = await _top("sql_examples", "question, sql")
    return {
        "ddl": [r[0] for r in ddl_rows],
        "docs": [r[0] for r in doc_rows],
        "examples": [{"question": r[0], "sql": r[1]} for r in example_rows],
    }
