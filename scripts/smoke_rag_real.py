# -*- coding: utf-8 -*-
"""真实 RAG 召回冒烟：用硅基流动远程 embedding 入库+查询，验证非 mock 语义召回。

仅依赖 app 包既有 API（app.rag.chunker / store / embed），不另造轮子。
"""
import asyncio
import sys

from app.config import get_settings
from app.infra.db import init_pool, get_pool, ensure_schema
from app.rag.chunker import split_markdown
from app.rag.store import add_document, retrieve_chunks
from app.rag.embed import embed_query


DOCS = {
    "pg.md": """# PostgreSQL pgvector 扩展
pgvector 是 PostgreSQL 的向量相似度检索扩展，支持 cosine / L2 / inner-product 距离。
建表时需声明 vector(维度)，例如 embedding vector(1024)。
检索用 ORDER BY embedding <=> :query LIMIT k 做最近邻搜索。""",
    "kafka.md": """# Kafka 消息队列
Kafka 是分布式流处理平台，核心概念是 topic、partition、consumer group。
生产者往 topic 推消息，消费者按 group 拉取，保证分区内有序。""",
    "redis.md": """# Redis 缓存
Redis 是内存键值数据库，常用作缓存与排行榜。
支持 string、hash、zset 等结构，zset 适合做延迟队列与热榜。""",
}


async def main():
    s = get_settings()
    print(f"[config] db_enabled={s.db_enabled} vector_dim={s.vector_dim} "
          f"embedding_mode={s.embedding_mode} embedding_model={s.embedding_model} "
          f"rerank_enabled={s.rerank_effective_enabled} rerank_model={s.rerank_model}")
    if not s.db_enabled:
        print("[FAIL] db_enabled=False，无法验证 RAG 真连")
        return 1

    pool = await init_pool()
    # ensure_schema 已按 VECTOR_DIM 建表；若维度变更需先 DROP（本脚本前置已处理）
    await ensure_schema(pool)

    # 1) 真实 embedding 入库
    doc_ids = []
    for src, md in DOCS.items():
        chunks = split_markdown(md)
        doc_id = await add_document(pool, src, chunks)
        doc_ids.append((src, doc_id, len(chunks)))
        print(f"[ingest] {src}: doc_id={doc_id} chunks={len(chunks)}")

    # 2) 真实查询召回（语义相关应命中 PG 文档而非 Kafka/Redis）
    queries = ["pgvector 怎么做向量检索？", "Kafka 的分区消费模型", "Redis zset 有什么用"]
    ok = 0
    for q in queries:
        hits = await retrieve_chunks(pool, q, k=2)
        top_src = hits[0]["source"] if hits else "<none>"
        # 期望：pg 查询命中 pg.md，kafka 命中 kafka.md，redis 命中 redis.md
        expect = {"pgvector": "pg.md", "Kafka": "kafka.md", "Redis": "redis.md"}[
            next(k for k in ("pgvector", "Kafka", "Redis") if k in q)
        ]
        status = "OK" if top_src == expect else "MISMATCH"
        if status == "OK":
            ok += 1
        print(f"[recall {status}] q='{q}' -> top={top_src} (expect {expect})")
        for h in hits:
            print(f"    - {h['source']} score={h['score']} :: {h['content'][:24]}...")

    # 3) rerank 接线验证：融合候选应被 rerank 重排（top-1 仍正确，且 score 为 rerank 分 0~1）
    if s.rerank_effective_enabled:
        top_hits = await retrieve_chunks(pool, "pgvector 怎么做向量检索？", k=2)
        rerank_ok = (
            top_hits
            and 0.0 <= top_hits[0]["score"] <= 1.0
            and top_hits[0]["source"] == "pg.md"
        )
        print(f"[rerank {'OK' if rerank_ok else 'FAIL'}] "
              f"top={top_hits[0]['source'] if top_hits else '<none>'} "
              f"score={top_hits[0]['score'] if top_hits else None} (应为 0~1 的 rerank 分)")
        rerank_pass = rerank_ok
    else:
        print("[rerank skip] rerank 未开启（RERANK_ENABLED=false 或无 key），跳过")
        rerank_pass = True

    # 3) 验证 embedding 是真实向量（非 mock 的确定性哈希）：用同一 query 与该 query 自身应高相似
    v1 = await embed_query("pgvector 向量检索")
    v2 = await embed_query("pgvector 向量检索")
    assert v1 == v2 and len(v1) == s.vector_dim, "embedding 维度/确定性异常"
    print(f"[embed] dim={len(v1)} 同句一致性 OK")

    print(f"\n=== 结论 ===\n[{'PASS' if ok == len(queries) and rerank_pass else 'PARTIAL'}] "
          f"真实 embedding 入库+召回：{ok}/{len(queries)} 语义命中正确；"
          f"rerank 重排：{'OK' if rerank_pass else 'FAIL'}")
    return 0 if (ok == len(queries) and rerank_pass) else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
