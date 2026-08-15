"""训练三件套存储：DDL / 业务文档 / (问题, SQL) 范例（Vanna 式持续训练）。

借鉴 Vanna 的核心机制：准确率来自"训练数据三件套 + 检索注入"，而非模型临场发挥。
不依赖已归档的 vanna 包，训练数据统一存 pgvector，按语义相似度召回。
"""

from app.infra.db import vector_search
from app.rag.embed import embed_query, embed_texts


async def store_ddl(pool, ddl: str) -> None:
    vec = (await embed_texts([ddl]))[0]
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO sql_ddl (content, embedding) VALUES (%s, %s)", (ddl, vec)
        )


async def store_doc(pool, doc: str) -> None:
    vec = (await embed_texts([doc]))[0]
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO sql_docs (content, embedding) VALUES (%s, %s)", (doc, vec)
        )


async def store_example(pool, question: str, sql: str) -> None:
    vec = (await embed_texts([question]))[0]
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO sql_examples (question, sql, embedding) VALUES (%s, %s, %s)",
            (question, sql, vec),
        )


async def fetch_context(pool, question: str, k: int = 3) -> dict:
    """按语义相似度召回最相关的 DDL / 文档 / 范例。"""
    if pool is None:
        return {"ddl": [], "docs": [], "examples": []}
    embedding = await embed_query(question)

    async def _top(table: str, cols: str) -> list:
        return await vector_search(pool, table, cols, embedding, k=k)

    ddl_rows = await _top("sql_ddl", "content")
    doc_rows = await _top("sql_docs", "content")
    example_rows = await _top("sql_examples", "question, sql")
    return {
        "ddl": [r[0] for r in ddl_rows],
        "docs": [r[0] for r in doc_rows],
        "examples": [{"question": r[0], "sql": r[1]} for r in example_rows],
    }
