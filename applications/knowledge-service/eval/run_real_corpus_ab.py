"""ADR-0017/T11：真实语料上的新旧词法路 A/B（自检索标注，可复跑）。

诚实声明：
- 语料来自现网 `product_manual_v4_bge_m3` 的 83 行真实文档（与 v3 同源）。
- 标注方式是 **self-retrieval canary**：从每篇文档自身抽取一段原文作为 query，并标注该文档为 relevant。
  这不是人工业务标注，只能衡量"机制是否保住领域词的精确召回"，不能替代人工 golden 的语义质量判决。
- 旧路 sparse 用 `agent_runtime.vector_sparse`（md5/TF 近似）代理 learned sparse；
  新路词法由 Milvus 引擎 BM25 + jieba 领域词典生成。

集合：`tok_ab_old_real`（本次新建，只含这 83 行副本）；新路直接查 `product_manual_v4_bge_m3`。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from agent_runtime.vector_sparse import build_sparse_vector
from pymilvus import AnnSearchRequest, DataType, MilvusClient, WeightedRanker

OLD = "tok_ab_old_real"
NEW = "product_manual_v4_bge_m3"
REPORT = Path(__file__).parent / "runs" / "real_corpus_ab.json"


def _query_from_content(content: str) -> str:
    for line in content.splitlines():
        text = re.sub(r"^[#\-\*>\s]+", "", line).strip()
        if len(text) >= 8:
            return text[:24]
    return re.sub(r"^[#\-\*>\s]+", "", content).strip()[:24]


def _metric(ranked: list[int], relevant: int, k: int) -> float:
    return 1.0 if relevant in ranked[:k] else 0.0


def main() -> int:
    c = MilvusClient(uri="http://milvus:19530")
    if not c.has_collection(NEW):
        print("前置不可用：新集合不存在", NEW)
        return 2

    rows = c.query(
        collection_name=NEW,
        filter="",
        limit=1000,
        output_fields=["chunk_id", "content", "dense_vector"],
    )
    if len(rows) < 10:
        print("前置不可用：语料不足", len(rows))
        return 2

    if not c.has_collection(OLD):
        s = c.create_schema(auto_id=False, enable_dynamic_fields=True)
        s.add_field(field_name="chunk_id", datatype=DataType.INT64, is_primary=True)
        s.add_field(field_name="content", datatype=DataType.VARCHAR, max_length=65535)
        s.add_field(field_name="dense_vector", datatype=DataType.FLOAT_VECTOR, dim=1024)
        s.add_field(field_name="sparse_vector", datatype=DataType.SPARSE_FLOAT_VECTOR)
        i = c.prepare_index_params()
        i.add_index(field_name="dense_vector", index_type="AUTOINDEX", metric_type="COSINE")
        i.add_index(field_name="sparse_vector", index_type="SPARSE_INVERTED_INDEX", metric_type="IP")
        c.create_collection(collection_name=OLD, schema=s, index_params=i)
        c.insert(
            collection_name=OLD,
            data=[
                {
                    "chunk_id": r["chunk_id"],
                    "content": r["content"],
                    "dense_vector": r["dense_vector"],
                    "sparse_vector": build_sparse_vector(r["content"]),
                }
                for r in rows
            ],
        )
        c.flush(OLD)
        import time

        time.sleep(3)

    cases = []
    for r in rows:
        q = _query_from_content(r["content"])
        if q:
            cases.append((r["chunk_id"], q))

    totals = {name: {"recall@5": 0.0, "recall@10": 0.0, "mrr": 0.0} for name in ("dense", "old_hybrid", "new_hybrid")}

    for relevant, query in cases:
        # 用该文档自身的 dense 作为 query 向量（self-retrieval 的稠密侧）。
        doc = c.query(
            collection_name=NEW,
            filter=f"chunk_id == {relevant}",
            limit=1,
            output_fields=["dense_vector"],
        )[0]
        dense_vec = doc["dense_vector"]

        dense_rank = c.search(
            collection_name=NEW, data=[dense_vec], anns_field="dense_vector",
            search_params={"metric_type": "COSINE"}, limit=10, output_fields=["chunk_id"],
        )[0]
        old_rank = c.hybrid_search(
            collection_name=OLD,
            reqs=[
                AnnSearchRequest(data=[dense_vec], anns_field="dense_vector", param={"metric_type": "COSINE"}, limit=10),
                AnnSearchRequest(
                    data=[build_sparse_vector(query)], anns_field="sparse_vector",
                    param={"metric_type": "IP"}, limit=10,
                ),
            ],
            ranker=WeightedRanker(0.8, 0.2, norm_score=True), limit=10, output_fields=["chunk_id"],
        )[0]
        new_rank = c.hybrid_search(
            collection_name=NEW,
            reqs=[
                AnnSearchRequest(data=[dense_vec], anns_field="dense_vector", param={"metric_type": "COSINE"}, limit=10),
                AnnSearchRequest(data=[query], anns_field="bm25_sparse", param={"metric_type": "BM25"}, limit=10),
            ],
            ranker=WeightedRanker(0.8, 0.2, norm_score=True), limit=10, output_fields=["chunk_id"],
        )[0]

        for name, ranked in (("dense", dense_rank), ("old_hybrid", old_rank), ("new_hybrid", new_rank)):
            ids = [
                int(h.get("id") or h["entity"].get("chunk_id") or h["entity"].get("id"))
                for h in ranked
            ]
            totals[name]["recall@5"] += _metric(ids, relevant, 5)
            totals[name]["recall@10"] += _metric(ids, relevant, 10)
            rank = ids.index(relevant) + 1 if relevant in ids else 0
            totals[name]["mrr"] += 1.0 / rank if rank else 0.0

    n = len(cases)
    report = {
        "disclaimer": "real-corpus self-retrieval canary; not human-labeled semantic golden",
        "corpus": NEW,
        "cases": n,
        "metrics": {k: {m: round(v[m] / n, 3) for m in v} for k, v in totals.items()},
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
