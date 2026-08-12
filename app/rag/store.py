"""分块存储与混合检索：pgvector 向量召回 + BM25 关键词召回 + RRF 融合。

MVP 阶段 BM25 语料在查询时全量加载（万级分块内可接受）；
规模上来后再替换为 ES/全文索引，检索接口保持不变。
"""

import re
import uuid

from rank_bm25 import BM25Okapi

from app.config import get_settings
from app.rag.chunker import Chunk
from app.rag.embed import embed_query, embed_texts

_BM25_LOAD_LIMIT = 10000


def tokenize(text: str) -> list[str]:
    """英文按词、中文按二元切分（免分词器依赖，MVP 够用）。"""
    text = text.lower()
    tokens = re.findall(r"[a-z0-9_]+", text)
    for seg in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(seg) == 1:
            tokens.append(seg)
        else:
            tokens.extend(seg[i : i + 2] for i in range(len(seg) - 1))
    return tokens


def rrf_merge(ranked_id_lists: list[list], k: int = 60) -> list:
    """Reciprocal Rank Fusion：多路召回按 1/(k+rank) 累加排序。"""
    scores: dict = {}
    for ranked in ranked_id_lists:
        for rank, item_id in enumerate(ranked, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=scores.get, reverse=True)


async def add_document(pool, source: str, chunks: list[Chunk]) -> str:
    """文档入库：向量化后批量插入；返回 doc_id。"""
    doc_id = uuid.uuid4().hex[:12]
    if not chunks:
        return doc_id
    vectors = await embed_texts([c.text for c in chunks])
    async with pool.connection() as conn:
        for chunk, vec in zip(chunks, vectors):
            await conn.execute(
                "INSERT INTO chunks (doc_id, source, heading, content, embedding) "
                "VALUES (%s, %s, %s, %s, %s)",
                (doc_id, source, chunk.heading, chunk.text, vec),
            )
    return doc_id


async def _vector_ids(pool, embedding: list[float], k: int) -> list[int]:
    sql = (
        "SELECT id FROM chunks WHERE embedding IS NOT NULL "
        "ORDER BY embedding <=> %s LIMIT %s"
    )
    async with pool.connection() as conn:
        cur = await conn.execute(sql, (embedding, k))
        rows = await cur.fetchall()
    return [r[0] for r in rows]


async def _bm25_ids(pool, query: str, k: int) -> list[int]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, content FROM chunks ORDER BY id LIMIT %s", (_BM25_LOAD_LIMIT,)
        )
        rows = await cur.fetchall()
    if not rows:
        return []
    corpus = [tokenize(r[1]) for r in rows]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(tokenize(query))
    order = sorted(range(len(rows)), key=lambda i: scores[i], reverse=True)
    return [rows[i][0] for i in order[:k] if scores[i] > 0]


async def retrieve_chunks(pool, query: str, k: int | None = None) -> list[dict]:
    """混合检索入口：返回 [{id, source, heading, content, score}]，已按 RRF 排序。"""
    if pool is None:
        return []
    k = k or get_settings().rag_top_k
    fetch_k = k * 4  # 每路多召回再融合
    embedding = await embed_query(query)
    vec_ids = await _vector_ids(pool, embedding, fetch_k)
    bm25_ids = await _bm25_ids(pool, query, fetch_k)
    merged = rrf_merge([vec_ids, bm25_ids])[:k]
    if not merged:
        return []
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, source, heading, content FROM chunks WHERE id = ANY(%s)",
            (list(merged),),
        )
        rows = await cur.fetchall()
    by_id = {r[0]: r for r in rows}
    return [
        {
            "id": chunk_id,
            "source": by_id[chunk_id][1],
            "heading": by_id[chunk_id][2],
            "content": by_id[chunk_id][3],
            "score": round(1.0 / (60 + rank), 6),
        }
        for rank, chunk_id in enumerate(merged, start=1)
        if chunk_id in by_id
    ]
