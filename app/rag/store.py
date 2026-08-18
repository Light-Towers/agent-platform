"""分块存储与混合检索：pgvector 向量召回 + BM25 关键词召回 + RRF 融合。

MVP 阶段 BM25 语料在查询时加载（万级分块内可接受）；
为降低重复开销，BM25 索引按 (行数, 最大 id) 签名缓存，语料变化即失效；
规模上来后再替换为 ES/全文索引，检索接口保持不变。
"""

import re
import uuid

from rank_bm25 import BM25Okapi

from app.config import get_settings
from app.infra.db import vector_search
from app.rag.chunker import Chunk
from app.rag.embed import embed_query, embed_texts
from app.rag.rerank import get_reranker

_BM25_LOAD_LIMIT = 10000
_RRF_K = 60

# BM25 索引缓存：signature=(count, max_id) -> (BM25Okapi, [id,...])
# 新增/删除 chunks 会改变签名从而失效；纯追加场景命中缓存避免每查询重建。
_BM25_CACHE: dict = {}


def _invalidate_bm25_cache() -> None:
    """语料变更后清空 BM25 缓存。"""
    _BM25_CACHE.clear()


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


def rrf_merge(ranked_id_lists: list[list], k: int = _RRF_K) -> list:
    """Reciprocal Rank Fusion：多路召回按 1/(k+rank) 累加排序。"""
    scores: dict = {}
    for ranked in ranked_id_lists:
        for rank, item_id in enumerate(ranked, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=scores.get, reverse=True)


async def add_document(pool, source: str, chunks: list[Chunk], workspace_id: str = "default") -> str:
    """文档入库：向量化后批量插入；返回 doc_id。

    workspace_id 隔离文档归属（优化 G）：不同工作空间上传的文档互不检索。
    """
    doc_id = uuid.uuid4().hex[:12]
    if not chunks:
        return doc_id
    vectors = await embed_texts([c.text for c in chunks])
    params = [
        (doc_id, source, c.heading, c.text, vec, workspace_id)
        for c, vec in zip(chunks, vectors)
    ]
    async with pool.connection() as conn:
        cur = conn.cursor()
        await cur.executemany(
            "INSERT INTO chunks (doc_id, source, heading, content, embedding, workspace_id) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            params,
        )
    _invalidate_bm25_cache()
    return doc_id


async def _vector_ids(pool, embedding: list[float], k: int, workspace_id: str = "default") -> list[int]:
    rows = await vector_search(
        pool, "chunks", "id", embedding, k=k,
        where="workspace_id = %s", where_params=(workspace_id,),
    )
    return [r[0] for r in rows]


async def _bm25_ids(pool, query: str, k: int, workspace_id: str = "default") -> list[int]:
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM chunks WHERE workspace_id = %s",
            (workspace_id,),
        )
        row = await cur.fetchone()
    count, max_id = (row[0], row[1]) if row else (0, 0)
    signature = (count, max_id, workspace_id)

    cached = _BM25_CACHE.get(signature)
    if cached is not None:
        bm25, ids = cached
    else:
        async with pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id, content FROM chunks WHERE workspace_id = %s ORDER BY id LIMIT %s",
                (workspace_id, _BM25_LOAD_LIMIT),
            )
            rows = await cur.fetchall()
        if not rows:
            _BM25_CACHE[signature] = (None, [])
            return []
        corpus = [tokenize(r[1]) for r in rows]
        bm25 = BM25Okapi(corpus)
        ids = [r[0] for r in rows]
        _BM25_CACHE[signature] = (bm25, ids)

    if bm25 is None:
        return []
    scores = bm25.get_scores(tokenize(query))
    order = sorted(range(len(ids)), key=lambda i: scores[i], reverse=True)
    return [ids[i] for i in order[:k] if scores[i] > 0]


async def retrieve_chunks(pool, query: str, k: int | None = None, workspace_id: str = "default") -> list[dict]:
    """混合检索入口：向量召回 + BM25 + RRF 融合，融合后可选 rerank 重排 top-K。

    workspace_id 隔离检索范围（优化 G）：仅召回本工作空间上传的文档分块。
    返回 [{id, source, heading, content, score}]，按相关性降序；
    rerank 开启时 score 为 rerank 相关性分（0~1），否则为 RRF 分。
    """
    if pool is None:
        return []
    s = get_settings()
    k = k or s.rag_top_k
    fetch_k = k * 4  # 每路多召回再融合
    embedding = await embed_query(query)
    vec_ids = await _vector_ids(pool, embedding, fetch_k, workspace_id)
    bm25_ids = await _bm25_ids(pool, query, fetch_k, workspace_id)
    merged = rrf_merge([vec_ids, bm25_ids])[: max(k, s.rerank_top_n)]
    if not merged:
        return []

    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, source, heading, content FROM chunks "
            "WHERE id = ANY(%s) AND workspace_id = %s",
            (list(merged), workspace_id),
        )
        rows = await cur.fetchall()
    by_id = {r[0]: r for r in rows}
    candidates = [by_id[c] for c in merged if c in by_id]
    if not candidates:
        return []

    # 融合后过 rerank 重排 top-K
    reranker = get_reranker()
    if reranker is not None:
        pairs = [[query, c[3]] for c in candidates]
        try:
            scores = reranker.compute_score(pairs)
        except Exception as e:  # rerank 失败则优雅回退到 RRF 融合序
            import logging

            logging.getLogger(__name__).warning("rerank 失败，回退 RRF 融合序: %s", e)
            scores = None
    else:
        scores = None

    if scores is not None:
        ordered = sorted(
            zip(candidates, scores), key=lambda x: x[1], reverse=True
        )[:k]
        return [
            {
                "id": c[0],
                "source": c[1],
                "heading": c[2],
                "content": c[3],
                "score": round(float(sc), 6),
            }
            for c, sc in ordered
        ]

    # 无 rerank：返回 RRF 融合序（截断到 k）
    return [
        {
            "id": c[0],
            "source": c[1],
            "heading": c[2],
            "content": c[3],
            "score": round(1.0 / (_RRF_K + rank), 6),
        }
        for rank, c in enumerate(candidates, start=1)
        if rank <= k
    ]
