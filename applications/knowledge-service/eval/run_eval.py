# -*- coding: utf-8 -*-
"""
检索评测运行器（M2，方案 §6.3）。

功能：
    读 ``eval/golden_queries.jsonl`` → 逐条调用检索链路（召回 → RRF 融合 → BGE 重排，
    **不含 LLM 生成，纯检索**）→ 计算指标（Recall@5 / Recall@10 / MRR / HitRate@5 /
    nDCG@10，按 grade 分级）→ 按 tags 分桶输出 → 生成 badcase 归档 → 回填索引 registry。

用法：
    python eval/run_eval.py --out eval/runs/ [--limit N] [--golden eval/golden_queries.jsonl]
                            [--enable-hyde] [--skip-rerank]

环境要求（重要）：
    - 依赖 Milvus（``knowledge_service/clients/milvus_utils.get_milvus_client``）且 **已运行 import_process
      建立索引**；Milvus 不可达或集合不存在时打印清晰错误并以非 0 退出码结束，**不吞异常**。
    - 依赖 BGE-M3 embedding 模型（检索向量化）；可选 BGE reranker（异常时节点自带降级为原序）。
    - HyDE 路默认关闭（需要 LLM 生成假设文档），用 ``--enable-hyde`` 显式开启。

输出：
    ``{out}/{timestamp}_{config_hash}/``
        - metrics.json     总分 + 按 tag 分桶
        - per_query.jsonl  每条 query 的召回列表与命中情况
        - badcases.md      未命中 / 低排名样本自动归档

诚实声明：本评测基于构造样例（见 golden_queries.jsonl 头注释），结果不代表线上指标；
所有数字为实测输出，本脚本不预填任何指标值。
"""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# 脚本直跑路径引导：`python eval/run_eval.py` 时把项目根加入 sys.path，
# 使 `knowledge_service.*` 可导入（uv run / 已安装 editable 包时此步为 no-op）。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from eval.ablation import fallback_config_hash  # noqa: E402 —— 纯 stdlib，供落后镜像降级用
from eval.metrics import compute_retrieval_metrics  # noqa: E402
from knowledge_service.clients.milvus_utils import (  # noqa: E402
    create_hybrid_search_requests,
    get_milvus_client,
    hybrid_search,
)

try:
    from knowledge_service.conf.config_hash import compute_config_hash  # noqa: E402 —— 单一实现已上收至 conf 包
except ModuleNotFoundError:
    # 部署镜像落后于工作树、缺 conf/config_hash；仅作归因标签/run_id 目录名，不影响检索数值。
    compute_config_hash = fallback_config_hash  # noqa: E402
from knowledge_service.conf.milvus_config import milvus_config  # noqa: E402 —— 路径引导后导入，脚本直跑必需
from knowledge_service.conf.retrieval_config import (  # noqa: E402 —— 全库兜底路与线上同参（dense/sparse 权重）
    retrieval_cfg,
)
from knowledge_service.core.tracing import init_tracing  # noqa: E402
from knowledge_service.lm.embedding_utils import generate_embeddings  # noqa: E402
from knowledge_service.query_process.agent.nodes.node_rerank import node_rerank  # noqa: E402
from knowledge_service.query_process.agent.nodes.node_rrf import _as_entity_list, reciprocal_rank_fusion  # noqa: E402
from knowledge_service.query_process.agent.nodes.node_search_embedding import node_search_embedding  # noqa: E402
from knowledge_service.query_process.agent.nodes.node_search_embedding_hyde import (  # noqa: E402
    node_search_embedding_hyde,
)

DEFAULT_GOLDEN: Path = Path(__file__).resolve().parent / "golden_queries.jsonl"
DEFAULT_OUT: Path = Path(__file__).resolve().parent / "runs"

# 评测输出文件
METRICS_FILE = "metrics.json"
PER_QUERY_FILE = "per_query.jsonl"
BADCASES_FILE = "badcases.md"


# ---------------------------------------------------------------------------
# golden 数据加载
# ---------------------------------------------------------------------------
def load_golden_queries(path: Path) -> List[Dict[str, Any]]:
    """
    读取 golden_queries.jsonl（跳过 ``#`` 开头的注释行）。

    返回：
        List[Dict] - 每条含 qid / query / item_name / relevant_chunk_ids / grade / tags。
    异常：
        FileNotFoundError - 文件不存在；
        json.JSONDecodeError - 某行 JSON 非法（不静默跳过，便于发现标注错误）。
    """
    if not path.exists():
        raise FileNotFoundError(f"golden 数据集不存在：{path}")
    queries: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                item = json.loads(stripped)
            except json.JSONDecodeError as e:
                raise json.JSONDecodeError(f"{path}:{line_no} JSON 解析失败: {e.msg}", e.doc, e.pos) from e
            queries.append(item)
    return queries


# ---------------------------------------------------------------------------
# 检索链路（纯检索，不含 LLM 生成）
# ---------------------------------------------------------------------------
def _extract_ids(docs: List[Dict[str, Any]]) -> List[str]:
    """从检索结果 dict 列表中提取 chunk_id（兼容 chunk_id / id / doc_id 字段）。"""
    ids: List[str] = []
    for doc in docs or []:
        if not isinstance(doc, dict):
            continue
        cid = doc.get("chunk_id") or doc.get("id") or doc.get("doc_id")
        if cid is not None:
            ids.append(str(cid))
    return ids


def _global_embedding_search(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    全库（无 item 过滤）embedding 检索 —— eval 侧独立实现，不改线上节点。

    背景：benchmark 语料的 chunk 普遍无 item_name（实测 product_manual_v1_bge_m3 全空）；
    工作树新版 node_search_embedding 对空 item_names 已是"不过滤、全库检索"，但落后部署镜像
    里的旧版会直接跳过返回空。此处用与消融 _embedding_route 同一批 Milvus 原语、与线上节点
    同一组参数（retrieval_cfg.hybrid 权重 / norm_score / output_fields）做全库检索，
    使 run_eval / run_e2e_eval 在新旧镜像上口径一致。
    """
    embeddings = generate_embeddings([query])
    dense_vec = embeddings.get("dense")[0]
    sparse_vec = embeddings.get("sparse")[0]
    reqs = create_hybrid_search_requests(
        dense_vector=dense_vec,
        sparse_vector=sparse_vec,
        expr=None,  # 全库：不带任何 item/租户过滤（benchmark 集合单租户）
        limit=max(limit * 3, 20),  # 底层候选留余量，与节点 candidate_limit 同理
    )
    res = hybrid_search(
        client=get_milvus_client(),
        collection_name=milvus_config.chunks_collection,
        reqs=reqs,
        ranker_weights=(retrieval_cfg.hybrid.dense_weight, retrieval_cfg.hybrid.sparse_weight),
        norm_score=True,
        limit=limit,
        output_fields=["chunk_id", "content", "item_name"],
    )
    return _as_entity_list(res[0]) if res else []


def retrieve_one(
    query: str,
    item_name: str,
    *,
    enable_hyde: bool = False,
    skip_rerank: bool = False,
) -> List[Dict[str, Any]]:
    """
    对单条 query 执行检索链路：embedding 召回（必跑）→（可选 HyDE 召回）→
    加权 RRF 融合 →（可选 BGE 重排，异常自动降级为原序）。

    参数：
        query: 用户问题（直接作为 rewritten_query 使用）
        item_name: 商品名（Milvus item_name 过滤依据）
        enable_hyde: 是否启用 HyDE 路（需 LLM，默认关闭）
        skip_rerank: 是否跳过重排（直接使用 RRF 顺序，适合无 reranker 环境）
    返回：
        List[Dict] - 最终排序的检索结果 dict 列表。
    """
    session_id = f"eval_{uuid.uuid4().hex[:12]}"
    state: Dict[str, Any] = {
        "session_id": session_id,
        "original_query": query,
        "rewritten_query": query,
        "item_names": [item_name] if item_name else [],
        "is_stream": False,
    }

    # 1) 召回：embedding 路（纯检索，无 LLM）。
    #    item_name 为空时走 eval 侧全库兜底（新节点本就是该语义；落后镜像的旧节点会
    #    误跳过返回空），与消融口径对齐；详见 _global_embedding_search docstring。
    if item_name:
        emb_result = node_search_embedding(state)
        emb_docs = _as_entity_list(emb_result.get("embedding_chunks"))
    else:
        emb_docs = _global_embedding_search(query)
    sources = [(emb_docs, 1.0)]

    # 2) 召回：HyDE 路（可选；节点自身在 LLM 失败时降级为空，不阻断）
    if enable_hyde:
        hyd_result = node_search_embedding_hyde(state)
        sources.append((_as_entity_list(hyd_result.get("hyde_embedding_chunks")), 1.0))

    # 3) 融合：加权 RRF（与线上链路同一函数、同一参数）
    fused = reciprocal_rank_fusion(sources, k=60, max_results=10)
    rrf_chunks = [doc for doc, _score in fused]

    if skip_rerank:
        return rrf_chunks

    # 4) 重排：BGE reranker + 动态 TopK（异常由节点降级为原序）
    rerank_state = dict(state)
    rerank_state["rrf_chunks"] = rrf_chunks
    rerank_state["web_search_docs"] = []
    reranked = node_rerank(rerank_state).get("reranked_docs", [])
    return reranked


# ---------------------------------------------------------------------------
# 指标聚合
# ---------------------------------------------------------------------------
def _mean(values: List[float]) -> float:
    """列表均值；空列表返回 0.0。"""
    return sum(values) / len(values) if values else 0.0


def aggregate_metrics(records: List[Dict[str, Any]]) -> Dict[str, float]:
    """对多条 per-query 指标记录求均值。"""
    keys = ["recall@5", "recall@10", "mrr", "hit_rate@5", "ndcg@10"]
    return {k: round(_mean([r["metrics"][k] for r in records]), 4) for k in keys}


def bucket_by_tag(records: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    按 tags 分桶（一条 query 可属多个 tag，这里按每条 query 的每个 tag 各计一次）。
    返回：tag -> {"sample_size": int, **aggregate_metrics}。
    """
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for rec in records:
        for tag in rec.get("tags") or []:
            buckets.setdefault(tag, []).append(rec)
    out: Dict[str, Dict[str, Any]] = {}
    for tag, recs in buckets.items():
        bucket = aggregate_metrics(recs)
        bucket["sample_size"] = len(recs)
        out[tag] = bucket
    return out


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------
def _write_json(path: Path, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def write_badcases(path: Path, records: List[Dict[str, Any]]) -> None:
    """自动 dump 未命中 / 低排名样本，供人工归因（方案 §6.5）。"""
    lines = [
        "# Badcases（自动归档）",
        "",
        "> 由 eval/run_eval.py 自动生成，供人工归因（切分劈答案 / HyDE 偏题 / 稀疏路对专有型号不敏感 / KG 缺实体等）。",
        "> 判定口径：recall@10 == 0 记为「未命中」；recall@10 > 0 但 mrr < 1.0 记为「低排名」。",
        "",
    ]
    bad = [r for r in records if r["metrics"]["recall@10"] == 0 or r["metrics"]["mrr"] < 1.0]
    if not bad:
        lines.append("_本 run 无 badcase。_")
    for rec in bad:
        kind = "未命中" if rec["metrics"]["recall@10"] == 0 else "低排名"
        lines.append(f"## {rec['qid']}（{kind}）")
        lines.append("")
        lines.append(f"- query: {rec['query']}")
        lines.append(f"- item_name: {rec['item_name']}")
        lines.append(f"- tags: {', '.join(rec.get('tags') or [])}")
        lines.append(f"- metrics: {json.dumps(rec['metrics'], ensure_ascii=False)}")
        lines.append(f"- relevant_chunk_ids: {rec['relevant_ids']}")
        lines.append(f"- retrieved_top5: {rec['retrieved_ids'][:5]}")
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def backfill_registry(run_id: str, overall: Dict[str, float]) -> None:
    """
    评测跑完后把得分回填到索引 registry 对应集合条目（方案 §5.4）。
    集合条目不存在（本地未跑过 import）时打印提示并跳过，不自动创建。
    """
    from knowledge_service.utils.index_registry import backfill_eval_scores

    collection = milvus_config.chunks_collection
    updated = backfill_eval_scores(
        collection,
        recall5=overall["recall@5"],
        mrr=overall["mrr"],
        ndcg10=overall["ndcg@10"],
        run_id=run_id,
    )
    if updated is None:
        print(f"[registry] 集合 {collection} 暂无 registry 条目，跳过得分回填（请先运行 import_process）")
    else:
        print(f"[registry] 已回填 {collection} 的评测得分 → run_id={run_id}")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="知识库检索评测运行器（M2）：逐条跑检索链路并计算 Recall/MRR/nDCG 指标。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="评测输出根目录")
    parser.add_argument("--limit", type=int, default=None, help="只评测前 N 条 query（调试用）")
    parser.add_argument("--golden", default=str(DEFAULT_GOLDEN), help="golden 数据集路径")
    parser.add_argument("--enable-hyde", action="store_true", help="启用 HyDE 召回路（需 LLM）")
    parser.add_argument("--skip-rerank", action="store_true", help="跳过 BGE 重排，直接使用 RRF 顺序")
    parser.add_argument(
        "--skip-sparse-check", action="store_true",
        help="跳过稀疏编码一致性 canary（仅调试；正常应让导入/查询编码不一致时 fail-fast）",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    golden_path = Path(args.golden)
    out_root = Path(args.out)

    # ---------- 环境守卫（Milvus 依赖，失败清晰报错并以非 0 退出，不吞异常） ----------
    collection_name = milvus_config.chunks_collection
    print(f"[eval] 目标集合：{collection_name}")

    # ---------- OTel 初始化（M4，方案 §8） ----------
    # 幂等；未配置 endpoint / 未启用时自动 no-op（评测默认不导出，需显式设置环境变量）。
    config_hash = compute_config_hash()
    init_tracing(config_hash=config_hash, collection=collection_name)

    client = get_milvus_client()
    if client is None:
        print(
            f"错误：无法连接 Milvus（{milvus_config.milvus_url}）。请先启动 Milvus 并确认 MILVUS_URL 配置。",
            file=sys.stderr,
        )
        return 1
    if not client.has_collection(collection_name=collection_name):
        print(
            f"错误：Milvus 集合 {collection_name} 不存在。"
            "请先运行 import_process 建立索引（node_import_milvus）后再执行评测。",
            file=sys.stderr,
        )
        return 1

    # ---------- 稀疏编码一致性 fail-fast（导入/查询 EMBEDDING_MODE 不一致时混合检索会静默退化为纯 dense） ----------
    if not args.skip_sparse_check:
        from knowledge_service.utils.sparse_consistency import (
            SparseEncodingMismatchError,
            assert_sparse_encoding_consistent,
        )

        try:
            assert_sparse_encoding_consistent(client, collection_name, use_cache=False)
        except SparseEncodingMismatchError as e:
            print(f"[eval] 稀疏编码门禁未通过，fail-fast（结果不可信）：\n  {e}", file=sys.stderr)
            return 1
        except Exception as e:  # noqa: BLE001 —— canary 自身环境异常（非错配判定）不阻断评测
            print(f"[eval] 警告：稀疏编码 canary 无法执行（非错配判定），跳过校验继续：{e}", file=sys.stderr)

    # ---------- 加载 golden ----------
    queries = load_golden_queries(golden_path)
    if args.limit is not None:
        queries = queries[: args.limit]
    if not queries:
        print(f"错误：golden 数据集 {golden_path} 无有效 query（请检查是否被注释或为空）。", file=sys.stderr)
        return 1
    print(f"[eval] 加载 {len(queries)} 条 golden query（来源：{golden_path}）")

    # ---------- 逐条评测 ----------
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    run_id = f"{timestamp}_{config_hash}"
    run_dir = out_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    records: List[Dict[str, Any]] = []
    for idx, item in enumerate(queries, start=1):
        qid = item.get("qid", f"q{idx:03d}")
        query = item.get("query", "")
        item_name = item.get("item_name", "")
        relevant_ids = [str(x) for x in (item.get("relevant_chunk_ids") or [])]
        grades = item.get("grade") or {}
        tags = item.get("tags") or []

        try:
            docs = retrieve_one(
                query,
                item_name,
                enable_hyde=args.enable_hyde,
                skip_rerank=args.skip_rerank,
            )
        except Exception as e:
            print(f"[eval] {qid} 检索链路异常：{e}", file=sys.stderr)
            raise

        retrieved_ids = _extract_ids(docs)
        metrics = compute_retrieval_metrics(retrieved_ids, relevant_ids, grades)
        records.append(
            {
                "qid": qid,
                "query": query,
                "item_name": item_name,
                "tags": tags,
                "retrieved_ids": retrieved_ids,
                "relevant_ids": relevant_ids,
                "metrics": metrics,
            }
        )
        print(f"[eval] {idx}/{len(queries)} {qid} {metrics}")

    # ---------- 聚合与输出 ----------
    overall = aggregate_metrics(records)
    by_tag = bucket_by_tag(records)

    metrics_data: Dict[str, Any] = {
        "run_id": run_id,
        "timestamp": timestamp,
        "config_hash": config_hash,
        "collection": collection_name,
        "golden": str(golden_path),
        "sample_size": len(records),
        "overall": overall,
        "by_tag": by_tag,
        "note": "基于构造样例评测；单桶样本<15 仅供定性参考；结果非线上指标（见 golden 头注释诚实声明）",
    }
    _write_json(run_dir / METRICS_FILE, metrics_data)

    with open(run_dir / PER_QUERY_FILE, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    write_badcases(run_dir / BADCASES_FILE, records)

    backfill_registry(run_id, overall)

    print(f"\n[eval] 完成：{run_dir}")
    print(f"[eval] overall = {json.dumps(overall, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
