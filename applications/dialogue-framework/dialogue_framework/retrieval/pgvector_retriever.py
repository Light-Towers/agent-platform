"""PgvectorRetriever：pgvector 向量检索生产实现。

复用 app/rag/store.py 既有 pgvector 查询模式（embedding <=> %s 余弦距离），
独立实现不改动 app/rag/。无 FAISS 依赖。
"""

from psycopg import AsyncConnection


class PgvectorRetriever:
    def __init__(self, conn: AsyncConnection, table: str = "dialogue_framework_chunks") -> None:
        self._conn = conn
        self._table = table

    async def retrieve(self, query: str, k: int = 4) -> list[dict]:
        from dialogue_framework.shared.llm.langchain_huggingface_embedder import build_embedder

        embedder = build_embedder()
        embedding = await embedder.embed_query(query)
        async with self._conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT id, content, embedding <=> %s AS distance
                FROM {self._table}
                ORDER BY distance
                LIMIT %s
                """,
                (embedding, k),
            )
            rows = await cur.fetchall()
        return [{"id": r[0], "content": r[1], "distance": float(r[2])} for r in rows]
