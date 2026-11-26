"""ADR-0017 / T10-T11：检索词法路 A/B 机制验证（POC，可复跑）。

【诚实声明】本脚本**不是**线上语义质量评测：
- 稠密向量用本机缓存的 `BAAI/bge-small-zh-v1.5`（512 维）代替 BGE-M3（1024 维），
  因为本机既无 BGE-M3 权重也无 SiliconFlow key；
- 旧路用 `agent_runtime.vector_sparse`（已登记待退役的 md5/TF 近似）模拟 learned sparse，
  不是 BGE-M3 原生 learned sparse；
- 因此结论只回答"两路机制是否按预期工作、领域词是否可被词法路召回"，
  **不回答"新方案检索质量优于旧方案"**。真实 E2 需模型/API 就绪后用 run_route_ablation.py 重跑。

集合：在给定 Milvus 上创建 `tok_ab_old` / `tok_ab_new` 两个独立集合（存在则复用，不删数据）。
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from agent_runtime.vector_sparse import build_sparse_vectors  # 已退役实现，仅作旧路基线代理
from pymilvus import AnnSearchRequest, DataType, Function, FunctionType, MilvusClient, WeightedRanker

GOLDEN = Path(__file__).parent / "golden_queries.zh_en_tokenizer.jsonl"

# (qid, query, 命中文档文本)；文档文本内嵌 query，保证两路都有可匹配词项。
CASES: list[tuple[str, str, str]] = [
    ("tok_001", "HAK-180 烫金机额定电压是多少", "HAK-180 烫金机额定电压是380V，属于工业烫印设备"),
    ("tok_002", "BGE-M3 sparse 向量怎么做召回", "BGE-M3 sparse 向量通过词项权重做召回，属于稀疏检索"),
    ("tok_003", "稠密向量和稀疏向量有什么区别", "稠密向量表示语义，稀疏向量表示词项权重，二者可以混合检索"),
    ("tok_004", "向量数据库混合检索怎么配置", "向量数据库混合检索需要配置稠密字段和稀疏字段以及融合权重"),
    ("tok_005", "烫金机的烫印温度上限", "烫金机烫印温度上限为200摄氏度，超过会损坏材料"),
    ("tok_006", "How to configure BGE-M3 dense retrieval", "BGE-M3 dense retrieval configuration uses cosine similarity"),
    ("tok_007", "SKU-9527 的保修期是多久", "SKU-9527 保修期为24个月，从购买日期起算"),
    ("tok_008", "sparse vector 和 BM25 有什么关系", "sparse vector 是稀疏向量表示，BM25 是词频统计打分方法"),
    # 难样本：查询与文档无同形词，考验语义路；词法路预期较弱。
    ("tok_009", "烫金机的功率是多少", "热压印设备额定功率为3kW，适合大批量连续作业"),
    ("tok_010", "这台机器最多能耐多热", "该设备最高工作温度为200摄氏度"),
    ("tok_011", "API 怎么对接", "系统提供开放式接口支持RESTful调用和鉴权"),
    ("tok_012", "质保多长时间", "产品保修期为24个月，自交付日起算"),
]
DISTRACTORS = [
    "今天天气很好适合出去散步",
    "公司年会筹备通知已发布",
    "数据库备份任务每日凌晨执行",
    "前端页面颜色需要调整",
]


def _load_golden_ids() -> set[str]:
    ids: set[str] = set()
    for line in GOLDEN.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        obj = json.loads(line)
        ids.add(obj["qid"])
    return ids


def _embed(texts: list[str]) -> list[list[float]]:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("BAAI/bge-small-zh-v1.5", local_files_only=True)
    vectors = model.encode(texts, normalize_embeddings=True)
    return [v.tolist() for v in vectors]


def _create_collections(client: MilvusClient, dim: int) -> tuple[Any, Any]:
    # 只重建本 POC 专用集合，保证每次跑数同一起点；绝不触碰生产集合。
    for name in ("tok_ab_old", "tok_ab_new"):
        if client.has_collection(name):
            client.drop_collection(name)
    old = client.create_schema(auto_id=False, enable_dynamic_fields=True)
    old.add_field(field_name="id", datatype=DataType.INT64, is_primary=True)
    old.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=4096)
    old.add_field(field_name="dense", datatype=DataType.FLOAT_VECTOR, dim=dim)
    old.add_field(field_name="sparse", datatype=DataType.SPARSE_FLOAT_VECTOR)
    i_old = client.prepare_index_params()
    i_old.add_index(field_name="dense", index_type="AUTOINDEX", metric_type="COSINE")
    i_old.add_index(field_name="sparse", index_type="SPARSE_INVERTED_INDEX", metric_type="IP")
    if not client.has_collection("tok_ab_old"):
        client.create_collection(collection_name="tok_ab_old", schema=old, index_params=i_old)

    new = client.create_schema(auto_id=False, enable_dynamic_fields=True)
    new.add_field(field_name="id", datatype=DataType.INT64, is_primary=True)
    new.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=4096, enable_analyzer=True,
                  analyzer_params={"tokenizer": "jieba"})
    new.add_field(field_name="dense", datatype=DataType.FLOAT_VECTOR, dim=dim)
    new.add_field(field_name="bm25_sparse", datatype=DataType.SPARSE_FLOAT_VECTOR)
    new.add_function(Function(name="bm25", function_type=FunctionType.BM25,
                              input_field_names=["text"], output_field_names=["bm25_sparse"]))
    i_new = client.prepare_index_params()
    i_new.add_index(field_name="dense", index_type="AUTOINDEX", metric_type="COSINE")
    i_new.add_index(field_name="bm25_sparse", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25")
    if not client.has_collection("tok_ab_new"):
        client.create_collection(collection_name="tok_ab_new", schema=new, index_params=i_new)
    return old, new


def _seed(client: MilvusClient, docs: list[tuple[int, str]], dim: int) -> None:
    dense = _embed([text for _id, text in docs])
    sparse = build_sparse_vectors([text for _id, text in docs])
    old_rows = [
        {"id": doc_id, "text": text, "dense": dense[i], "sparse": sparse[i]}
        for i, (doc_id, text) in enumerate(docs)
    ]
    new_rows = [
        {"id": doc_id, "text": text, "dense": dense[i]}
        for i, (doc_id, text) in enumerate(docs)
    ]
    if client.has_collection("tok_ab_old") and client.get_collection_stats("tok_ab_old")["row_count"] == 0:
        client.insert(collection_name="tok_ab_old", data=old_rows)
        client.flush("tok_ab_old")
    if client.has_collection("tok_ab_new") and client.get_collection_stats("tok_ab_new")["row_count"] == 0:
        client.insert(collection_name="tok_ab_new", data=new_rows)
        client.flush("tok_ab_new")
    time.sleep(3)  # 等索引就绪；刚插入即查会出现 0 命中（T2 实测）


def _search(client: MilvusClient, collection: str, query: str, dense_vec: list[float], mode: str) -> list[int]:
    dense_req = AnnSearchRequest(data=[dense_vec], anns_field="dense", param={"metric_type": "COSINE"}, limit=10)
    if mode == "dense_only":
        res = client.search(collection_name=collection, data=[dense_vec], anns_field="dense",
                            search_params={"metric_type": "COSINE"}, limit=10, output_fields=["id"])
        return [int(h["id"]) for h in res[0]]
    if mode == "old_sparse_only":
        sparse = build_sparse_vectors([query])[0]
        res = client.search(collection_name="tok_ab_old", data=[sparse], anns_field="sparse",
                            search_params={"metric_type": "IP"}, limit=10, output_fields=["id"])
        return [int(h["id"]) for h in res[0]]
    if mode == "new_bm25_only":
        res = client.search(collection_name="tok_ab_new", data=[query], anns_field="bm25_sparse",
                            search_params={"metric_type": "BM25"}, limit=10, output_fields=["id"])
        return [int(h["id"]) for h in res[0]]
    if mode == "old_hybrid":
        sparse = build_sparse_vectors([query])[0]
        lex_req = AnnSearchRequest(data=[sparse], anns_field="sparse", param={"metric_type": "IP"}, limit=10)
    else:
        lex_req = AnnSearchRequest(data=[query], anns_field="bm25_sparse", param={"metric_type": "BM25"}, limit=10)
    res = client.hybrid_search(
        collection_name=collection, reqs=[dense_req, lex_req],
        ranker=WeightedRanker(0.8, 0.2, norm_score=True), limit=10, output_fields=["id"],
    )
    return [int(h["id"]) for h in res[0]]


def _recall(ranked: list[int], relevant: int, k: int) -> float:
    return 1.0 if relevant in ranked[:k] else 0.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", required=True)
    parser.add_argument("--model", default="BAAI/bge-small-zh-v1.5")
    args = parser.parse_args(argv)

    golden_ids = _load_golden_ids()
    missing = {c[0] for c in CASES} - golden_ids
    if missing:
        print(f"前置不可用：golden 缺样本 {sorted(missing)}")
        return 2

    client = MilvusClient(uri=args.uri)
    docs = [(i, text) for i, (_qid, _query, text) in enumerate(CASES)]
    docs += [(100 + i, text) for i, text in enumerate(DISTRACTORS)]
    dim = len(_embed(["probe"])[0])
    _create_collections(client, dim)
    _seed(client, docs, dim)

    queries = [q for _id, q, _text in CASES]
    q_vectors = _embed(queries)
    report: dict[str, Any] = {
        "disclaimer": "mechanics-only: bge-small-zh-v1.5 + md5/TF proxy; not BGE-M3 quality result",
        "dim": dim,
        "cases": [],
    }
    for i, (qid, query, _text) in enumerate(CASES):
        relevant = i
        row: dict[str, Any] = {"qid": qid, "query": query, "relevant_id": relevant}
        for mode, collection in (
            ("dense_only", "tok_ab_new"),
            ("old_sparse_only", "tok_ab_old"),
            ("new_bm25_only", "tok_ab_new"),
            ("old_hybrid", "tok_ab_old"),
            ("new_hybrid", "tok_ab_new"),
        ):
            ranked = _search(client, collection, query, q_vectors[i], mode)
            rank = ranked.index(relevant) + 1 if relevant in ranked else 0
            row[mode] = {
                "ranked_ids": ranked,
                "rank": rank,
                "mrr": 1.0 / rank if rank else 0.0,
                "recall@5": _recall(ranked, relevant, 5),
                "recall@10": _recall(ranked, relevant, 10),
            }
        report["cases"].append(row)

    modes = ("dense_only", "old_sparse_only", "new_bm25_only", "old_hybrid", "new_hybrid")
    for mode in modes:
        report[f"{mode}_recall@5"] = sum(c[mode]["recall@5"] for c in report["cases"]) / len(CASES)
        report[f"{mode}_recall@10"] = sum(c[mode]["recall@10"] for c in report["cases"]) / len(CASES)
        report[f"{mode}_mrr"] = sum(c[mode]["mrr"] for c in report["cases"]) / len(CASES)

    out = Path(__file__).parent / "runs" / "tokenizer_ab_poc.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for mode in modes:
        print(
            f"{mode}: recall@5={report[f'{mode}_recall@5']:.3f} "
            f"recall@10={report[f'{mode}_recall@10']:.3f} mrr={report[f'{mode}_mrr']:.3f}"
        )
    print(f"REPORT {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
