"""分块存储与混合检索：pgvector 向量召回 + BM25 关键词召回 + RRF 融合。

MVP 阶段 BM25 语料在查询时加载（万级分块内可接受）；
为降低重复开销，BM25 索引按 (行数, 最大 id) 签名缓存，语料变化即失效；
规模上来后再替换为 ES/全文索引，检索接口保持不变。

隔离契约（ADR-0006 T9/W1）：chunks 以 ``tenant_id`` 为安全边界、
``workspace_id`` 为归属维，所有读写谓词成对出现；tenant 漏传经
``_tenant_gate.resolve_tenant`` fail-fast，绝不静默落共享 default 桶。
"""

import uuid

from agent_core.memory._tenant_gate import _TENANT_UNSET, resolve_tenant
from agent_runtime.db import vector_search
from agent_runtime.retrieval_tokenizer import get_tokenizer
from rank_bm25 import BM25Okapi

from agent_server.config import get_settings
from agent_server.rag.chunker import Chunk
from agent_server.rag.embed import embed_query, embed_texts
from agent_server.rag.rerank import get_reranker

_BM25_LOAD_LIMIT = 10000
_RRF_K = 60

# BM25 索引缓存：signature=(count, max_id) -> (BM25Okapi, [id,...])
# 新增/删除 chunks 会改变签名从而失效；纯追加场景命中缓存避免每查询重建。
_BM25_CACHE: dict = {}


def _invalidate_bm25_cache() -> None:
    """语料变更后清空 BM25 缓存。"""
    _BM25_CACHE.clear()


def rrf_merge(ranked_id_lists: list[list], k: int = _RRF_K) -> list:
    """Reciprocal Rank Fusion：多路召回按 1/(k+rank) 累加排序。"""
    scores: dict = {}
    for ranked in ranked_id_lists:
        for rank, item_id in enumerate(ranked, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=scores.get, reverse=True)


async def add_document(
    pool, source: str, chunks: list[Chunk], workspace_id: str = "default", knowledge_id: str = "", *, tenant_id: str = _TENANT_UNSET,
) -> str:
    """文档入库：向量化后批量插入；返回 doc_id。

    隔离双维（ADR-0006 T9）：``tenant_id`` 安全边界（服务端上下文，漏传即抛）；
    ``workspace_id`` 归属维（优化 G）：同租户内不同工作空间上传的文档互不检索。
    ``knowledge_id`` 归属维（plan-knowledge-base-model）：多知识库登记，空 = 未归属。
    """
    tenant_id = resolve_tenant(tenant_id)
    doc_id = uuid.uuid4().hex[:12]
    if not chunks:
        return doc_id
    vectors = await embed_texts([c.text for c in chunks])
    params = [
        # 末位固定 workspace_id：governance/test_workspace_isolation.py 钉住「首位 tenant_id
        # + 末位 workspace_id」的元组形状 ⇒ knowledge_id/status 必须排在它前面。
        # v3 软删除：新写入 status='active'。
        (tenant_id, doc_id, source, c.heading, c.text, vec, knowledge_id, "active", workspace_id)
        for c, vec in zip(chunks, vectors)
    ]
    async with pool.connection() as conn:
        cur = conn.cursor()
        await cur.executemany(
            "INSERT INTO chunks (tenant_id, doc_id, source, heading, content, embedding, knowledge_id, status, workspace_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            params,
        )
    _invalidate_bm25_cache()
    return doc_id


async def delete_document(
    pool, doc_id: str, workspace_id: str = "default", *, tenant_id: str = _TENANT_UNSET,
) -> int:
    """删除文档及其所有分块（与 add_document 对称）。返回删除行数。"""
    tenant_id = resolve_tenant(tenant_id)
    async with pool.connection() as conn:
        cur = await conn.execute(
            "DELETE FROM chunks WHERE tenant_id = %s AND doc_id = %s AND workspace_id = %s",
            (tenant_id, doc_id, workspace_id),
        )
        deleted = cur.rowcount
    if deleted:
        _invalidate_bm25_cache()
    return deleted


def _scope_predicate(workspace_id: str, knowledge_id: str) -> tuple[str, tuple]:
    """归属维谓词（workspace_id 必有；knowledge_id 空 = 不过滤，即全部知识库）。

    归属维不掺安全边界：tenant_id 谓词由各调用点单独成对携带（ADR-0006 T9）。
    """
    where = "workspace_id = %s AND status != 'REVOKED'"
    params: list = [workspace_id]
    if knowledge_id:
        where += " AND knowledge_id = %s"
        params.append(knowledge_id)
    return where, tuple(params)


async def _vector_ids(
    pool, embedding: list[float], k: int, workspace_id: str = "default", knowledge_id: str = "", *, tenant_id: str = _TENANT_UNSET,
) -> list[int]:
    tenant_id = resolve_tenant(tenant_id)
    scope_where, scope_params = _scope_predicate(workspace_id, knowledge_id)
    rows = await vector_search(
        pool, "chunks", "id", embedding, k=k,
        where=f"tenant_id = %s AND {scope_where}", where_params=(tenant_id, *scope_params),
    )
    return [r[0] for r in rows]


async def _bm25_ids(
    pool, query: str, k: int, workspace_id: str = "default", knowledge_id: str = "", *, tenant_id: str = _TENANT_UNSET,
) -> list[int]:
    tenant_id = resolve_tenant(tenant_id)
    scope_where, scope_params = _scope_predicate(workspace_id, knowledge_id)
    async with pool.connection() as conn:
        cur = await conn.execute(
            f"SELECT COUNT(*), COALESCE(MAX(id), 0) FROM chunks "
            f"WHERE tenant_id = %s AND {scope_where}",
            (tenant_id, *scope_params),
        )
        row = await cur.fetchone()
    count, max_id = (row[0], row[1]) if row else (0, 0)
    signature = (count, max_id, tenant_id, workspace_id, knowledge_id)

    cached = _BM25_CACHE.get(signature)
    if cached is not None:
        bm25, ids = cached
    else:
        async with pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT id, content FROM chunks WHERE tenant_id = %s AND {scope_where} "
                f"ORDER BY id LIMIT %s",
                (tenant_id, *scope_params, _BM25_LOAD_LIMIT),
            )
            rows = await cur.fetchall()
        if not rows:
            _BM25_CACHE[signature] = (None, [])
            return []
        corpus = [get_tokenizer().tokenize(r[1]) for r in rows]
        bm25 = BM25Okapi(corpus)
        ids = [r[0] for r in rows]
        _BM25_CACHE[signature] = (bm25, ids)

    if bm25 is None:
        return []
    scores = bm25.get_scores(get_tokenizer().tokenize(query))
    order = sorted(range(len(ids)), key=lambda i: scores[i], reverse=True)
    return [ids[i] for i in order[:k] if scores[i] > 0]


async def retrieve_chunks(
    pool, query: str, k: int | None = None, workspace_id: str = "default", knowledge_id: str = "", *, tenant_id: str = _TENANT_UNSET,
) -> list[dict]:
    """混合检索入口：向量召回 + BM25 + RRF 融合，融合后可选 rerank 重排 top-K。

    隔离双维（ADR-0006 T9）：仅召回本租户本工作空间上传的文档分块；
    tenant 精确谓词，不做 default 桶过渡读（归属宁可不可见，不跨租户可见）。
    ``knowledge_id`` 归属维（空 = 全部知识库）；过滤谓词成对出现，缺省不过滤。
    返回 [{id, source, heading, content, score}]，按相关性降序；
    rerank 开启时 score 为 rerank 相关性分（0~1），否则为 RRF 分。
    """
    if pool is None:
        return []
    tenant_id = resolve_tenant(tenant_id)
    s = get_settings()
    k = k or s.rag_top_k
    fetch_k = k * 4  # 每路多召回再融合
    embedding = await embed_query(query)
    vec_ids = await _vector_ids(pool, embedding, fetch_k, workspace_id, knowledge_id, tenant_id=tenant_id)
    bm25_ids = await _bm25_ids(pool, query, fetch_k, workspace_id, knowledge_id, tenant_id=tenant_id)
    merged = rrf_merge([vec_ids, bm25_ids])[: max(k, s.rerank_top_n)]
    if not merged:
        return []

    scope_where, scope_params = _scope_predicate(workspace_id, knowledge_id)
    async with pool.connection() as conn:
        cur = await conn.execute(
            f"SELECT id, source, heading, content FROM chunks "
            f"WHERE tenant_id = %s AND id = ANY(%s) AND {scope_where}",
            (tenant_id, list(merged), *scope_params),
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
        except Exception as e:
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
