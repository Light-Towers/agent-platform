# -*- coding: utf-8 -*-
"""
端到端 RAG 评测运行器（Phase C1）：检索 → 组上下文 → LLM 生成 → 答案质量打分。

与只到"召回对不对"为止的 run_eval.py / run_route_ablation.py 不同，本脚本把链路拉到
"答案好不好"，并**把检索层与生成层分开出报表**（归因分离：改了召回知道锅在检索还是生成）。

链路（逐 query）：
    1. 检索：复用 run_eval.retrieve_one（embedding(+HyDE) → 加权 RRF → BGE 重排）。
    2. 检索层指标：compute_retrieval_metrics（recall/ndcg/... 对 relevant_chunk_ids）。
    3. 组上下文：scorers.build_context（按 max_chars 截断，喂 LLM 的边界产物）。
    4. 生成：get_llm_client().invoke(default_answer_prompt) → answer。
    5. 生成层打分：scorer.score(query, context, answer, reference) → faithfulness/relevance/correctness。

诚实声明（防伪造，务必读）：
    - **无 LLM key / LLM 不可达** → 生成层整体标 skipped（检索层仍实测），不拿空答案凑分。
    - golden 缺 `reference_answer` → correctness 记 None（不计均值）。
    - 某条检索/生成异常 → 该条对应层标 skipped，绝不预填数字。

前置：目标集合须已建索引（真实语料走 node_import_milvus；或先跑 seed_synthetic_corpus.py）。
用真实 golden：先 `python eval/gen_golden.py ...` 产出 `golden_queries.real.jsonl`（含 reference_answer）。

用法：
    python eval/run_e2e_eval.py --golden eval/golden_queries.real.jsonl [--scorer judge]
                                [--limit N] [--out eval/runs] [--enable-hyde] [--skip-rerank]
                                [--max-context-chars 6000]

实现说明：重型 import（Milvus / run_eval / LLM）延迟到执行期；`--help` 任何环境可打印。
"""

import argparse
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# 脚本直跑路径引导。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 纯 stdlib 依赖可早导入（scorers 内部对 LLM/Milvus 皆惰性）。
from eval.ablation import fallback_config_hash  # noqa: E402
from eval.scorers import (  # noqa: E402
    DIMS,
    aggregate_scores,
    build_context,
    default_answer_prompt,
    make_scorer,
)

DEFAULT_GOLDEN: Path = Path(__file__).resolve().parent / "golden_queries.real.jsonl"
DEFAULT_OUT: Path = Path(__file__).resolve().parent / "runs"
REPORT_FILE = "e2e_report.md"
PER_QUERY_FILE = "e2e_per_query.jsonl"
METRICS_FILE = "e2e_metrics.json"
RETRIEVAL_KEYS: tuple = ("recall@5", "recall@10", "mrr", "hit_rate@5", "ndcg@10")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="端到端 RAG 评测运行器：检索 → 生成 → 答案质量打分（检索层/生成层分离报表）。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--golden", default=str(DEFAULT_GOLDEN), help="golden 数据集路径（真实 chunk_id + reference_answer）")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="评测输出根目录")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 条 query（调试用）")
    parser.add_argument("--scorer", default="judge", choices=["judge", "heuristic"], help="生成层打分器（judge=LLM-as-judge；heuristic=词面确定性基线）")
    parser.add_argument("--max-context-chars", type=int, default=6000, help="组上下文的字符上限（截断防超窗）")
    parser.add_argument("--enable-hyde", action="store_true", help="检索链路启用 HyDE 路（需 LLM）")
    parser.add_argument("--skip-rerank", action="store_true", help="检索链路跳过 BGE 重排，直接用 RRF 顺序")
    parser.add_argument(
        "--skip-sparse-check", action="store_true",
        help="跳过稀疏编码一致性 canary（仅调试；正常应让导入/查询编码不一致时 fail-fast）",
    )
    parser.add_argument(
        "--llm-timeout", type=float, default=90.0,
        help="单次外部 LLM/重排调用（检索 rerank、生成、judge）墙钟超时秒数；超时则该条对应层标 skipped 不阻断其余（防外部 API 无响应挂死整轮）",
    )
    return parser.parse_args(argv)


def _load_deps() -> Dict[str, Any]:
    """延迟加载 Milvus / 检索 / LLM 重型依赖（保证 --help 可打印）。"""
    from eval.metrics import compute_retrieval_metrics
    from eval.run_eval import (
        _extract_ids,
        aggregate_metrics,
        bucket_by_tag,
        load_golden_queries,
        retrieve_one,
    )
    from knowledge_service.clients.milvus_utils import get_milvus_client
    from knowledge_service.conf.milvus_config import milvus_config
    from knowledge_service.core.tracing import init_tracing

    try:
        from knowledge_service.conf.config_hash import compute_config_hash
    except ModuleNotFoundError:
        compute_config_hash = fallback_config_hash

    return {
        "compute_retrieval_metrics": compute_retrieval_metrics,
        "extract_ids": _extract_ids,
        "load_golden_queries": load_golden_queries,
        "retrieve_one": retrieve_one,
        "aggregate_metrics": aggregate_metrics,
        "bucket_by_tag": bucket_by_tag,
        "get_milvus_client": get_milvus_client,
        "milvus_config": milvus_config,
        "init_tracing": init_tracing,
        "compute_config_hash": compute_config_hash,
    }


def _get_llm(json_mode: bool):
    """惰性取统一 LLM 客户端（生成用非 json，judge scorer 内部自取 json 客户端）。"""
    from knowledge_service.lm.lm_utils import get_llm_client

    return get_llm_client(json_mode=json_mode)


def _call_with_timeout(fn, timeout: float):
    """在守护线程执行外部 I/O 并施加墙钟超时。

    外部 API（SiliconFlow rerank/生成/judge）无响应挂起时不会抛异常，故常规 try/except 兜不住；
    本函数超时抛 ``TimeoutError``，由上层按条标 skipped（诚实降级，不伪造分数、不阻断其余 query）。
    worker 线程设为 daemon：卡住的线程不会阻塞进程退出（长任务收尾随主进程回收）。
    """
    box: Dict[str, Any] = {}

    def _worker():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 —— 透传任何 worker 异常给主线程统一处理
            box["error"] = exc

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f"外部调用超过 {timeout}s 未完成（API 疑似挂起）")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _generation_bucket_summary(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """按 tag 分桶生成层得分（一条 query 多 tag 各计一次；与检索层分桶口径一致）。"""
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for rec in records:
        for tag in rec.get("tags") or []:
            buckets.setdefault(tag, []).append(rec["generation"])
    return {tag: aggregate_scores(recs) for tag, recs in buckets.items()}


def _render_report(
    run_id: str,
    config_hash: str,
    collection: str,
    golden: str,
    sample_size: int,
    args: argparse.Namespace,
    retrieval_overall: Dict[str, float],
    retrieval_by_tag: Dict[str, Any],
    generation_overall: Dict[str, Any],
    generation_by_tag: Dict[str, Any],
    gen_skipped: bool,
    gen_skip_reason: str,
) -> str:
    lines: List[str] = [
        "# 端到端 RAG 评测报告（检索层 / 生成层归因分离）",
        "",
        f"- run_id: `{run_id}`",
        f"- config_hash: `{config_hash}`",
        f"- collection: `{collection}`",
        f"- golden: `{golden}`",
        f"- sample_size: {sample_size}（单桶样本可能 <15，仅定性方向，非线上指标）",
        f"- scorer: `{args.scorer}` | hyde: {args.enable_hyde} | skip_rerank: {args.skip_rerank} | max_context_chars: {args.max_context_chars}",
        "",
        "## 检索层（召回对不对：对 relevant_chunk_ids 的排序质量）",
        "",
        "| 指标 | 值 |",
        "|---|---|",
    ]
    for k in RETRIEVAL_KEYS:
        lines.append(f"| {k} | {retrieval_overall.get(k)} |")

    if retrieval_by_tag:
        lines += ["", "### 检索层分桶（by tag）", "", "| tag | " + " | ".join(RETRIEVAL_KEYS) + " | n |", "|---|" + "---|" * (len(RETRIEVAL_KEYS) + 1)]
        for tag, b in retrieval_by_tag.items():
            row = " | ".join(str(b.get(k)) for k in RETRIEVAL_KEYS)
            lines.append(f"| {tag} | {row} | {b.get('sample_size')} |")

    lines += ["", "## 生成层（答案好不好：faithfulness / relevance / correctness，值域 0..1）", ""]
    if gen_skipped:
        lines += [f"_生成层未评测：{gen_skip_reason}（检索层数字仍有效，归因分离不互相污染）。_", ""]
    else:
        lines += ["| 维度 | 均值 | 有效样本 n |", "|---|---|---|"]
        for dim in DIMS:
            info = generation_overall.get(dim, {})
            lines.append(f"| {dim} | {info.get('mean')} | {info.get('n')} |")
        if generation_by_tag:
            lines += ["", "### 生成层分桶（by tag）", "", "| tag | " + " | ".join(DIMS) + "（均值/n） |", "|---|" + "---|" * len(DIMS)]
            for tag, b in generation_by_tag.items():
                cells = " | ".join(
                    f"{(b.get(dim) or {}).get('mean')}/{(b.get(dim) or {}).get('n')}" for dim in DIMS
                )
                lines.append(f"| {tag} | {cells} |")

    lines += [
        "",
        "## 诚实声明与口径",
        "",
        "- **归因分离**：检索差 ≠ 生成差。检索层低 → 召回/排序问题；检索层高但生成层低 → 生成/上下文组织问题。",
        "- faithfulness/relevance/correctness 由 `--scorer` 选定实现打分（judge=LLM-as-judge，heuristic=词面基线）；judge 选型对比见 Phase C2 `meta_eval_judge.py`。",
        "- 缺 reference_answer → correctness 记 None 不计均值；LLM 不可达 → 生成层整体 skipped，绝不拿空答案凑分。",
        "- 数字全部实测，本脚本不预填任何指标值。",
        "",
    ]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    deps = _load_deps()
    golden_path = Path(args.golden)
    out_root = Path(args.out)

    collection_name = deps["milvus_config"].chunks_collection
    print(f"[e2e] 目标集合：{collection_name}")

    # ---------- 环境守卫（Milvus 不可达 / 集合不存在 → 清晰报错 return 1，不吞异常） ----------
    client = deps["get_milvus_client"]()
    if client is None:
        print(
            f"错误：无法连接 Milvus（{deps['milvus_config'].milvus_url}）。请先启动 Milvus 并确认 MILVUS_URL 配置。",
            file=sys.stderr,
        )
        return 1
    if not client.has_collection(collection_name=collection_name):
        print(
            f"错误：Milvus 集合 {collection_name} 不存在。请先建索引"
            "（真实语料 node_import_milvus / 合成 seed_synthetic_corpus.py）后再跑端到端。",
            file=sys.stderr,
        )
        return 1

    config_hash = deps["compute_config_hash"]()
    deps["init_tracing"](config_hash=config_hash, collection=collection_name)

    # ---------- 稀疏编码一致性 fail-fast（检索层会因导入/查询编码不一致静默退化为纯 dense） ----------
    if not args.skip_sparse_check:
        from knowledge_service.utils.sparse_consistency import (
            SparseEncodingMismatchError,
            assert_sparse_encoding_consistent,
        )

        try:
            assert_sparse_encoding_consistent(client, collection_name, use_cache=False)
        except SparseEncodingMismatchError as e:
            print(f"[e2e] 稀疏编码门禁未通过，fail-fast（检索层数字不可信）：\n  {e}", file=sys.stderr)
            return 1
        except Exception as e:  # noqa: BLE001 —— canary 自身环境异常（非错配判定）不阻断评测
            print(f"[e2e] 警告：稀疏编码 canary 无法执行（非错配判定），跳过校验继续：{e}", file=sys.stderr)

    queries = deps["load_golden_queries"](golden_path)
    if args.limit is not None:
        queries = queries[: args.limit]
    if not queries:
        print(f"错误：golden 数据集 {golden_path} 无有效 query。", file=sys.stderr)
        return 1
    print(f"[e2e] 加载 {len(queries)} 条 golden query（来源：{golden_path}）")

    # ---------- 生成层能力探测（无 LLM → 生成层整体 skipped，检索层仍实测） ----------
    gen_llm = None
    gen_skip_reason = ""
    try:
        gen_llm = _get_llm(json_mode=False)
        # 轻量探活：构造成功即认为可用（真正失败在逐条 invoke 时按条降级）。
    except Exception as e:  # noqa: BLE001 —— LLM 客户端构造失败属环境缺失，诚实标注不阻断检索层
        gen_skip_reason = f"LLM 客户端不可用：{e}"
        print(f"[e2e] 警告：{gen_skip_reason} → 生成层整体标 skipped（检索层仍实测）。", file=sys.stderr)

    scorer = make_scorer(args.scorer, llm=_get_llm(json_mode=True) if (args.scorer == "judge" and gen_llm) else None)

    records: List[Dict[str, Any]] = []
    retrieval_records: List[Dict[str, Any]] = []
    for idx, item in enumerate(queries, start=1):
        qid = item.get("qid", f"q{idx:03d}")
        query = item.get("query", "")
        item_name = item.get("item_name", "")
        relevant_ids = [str(x) for x in (item.get("relevant_chunk_ids") or [])]
        grades = item.get("grade") or {}
        tags = item.get("tags") or ([item["tag"]] if item.get("tag") else [])
        reference = item.get("reference_answer")

        # ---- 检索层 ----
        try:
            docs = _call_with_timeout(
                lambda: deps["retrieve_one"](query, item_name, enable_hyde=args.enable_hyde, skip_rerank=args.skip_rerank),
                args.llm_timeout,
            )
        except Exception as e:  # noqa: BLE001 —— 检索链路外部 I/O（Milvus/rerank API），异常/超时面宽，该条标 skipped 不阻断其余
            print(f"[e2e] {qid} 检索异常/超时，跳过：{e}", file=sys.stderr)
            docs = []
        retrieved_ids = deps["extract_ids"](docs)
        retrieval_metrics = deps["compute_retrieval_metrics"](retrieved_ids, relevant_ids, grades)
        retrieval_records.append({"qid": qid, "query": query, "tags": tags, "metrics": retrieval_metrics})

        # ---- 生成层 ----
        generation: Dict[str, Any]
        answer = ""
        context = build_context(docs, max_chars=args.max_context_chars)
        if gen_llm is None:
            generation = {**{d: None for d in DIMS}, "reasons": {}, "skipped": True}
        else:
            prompt = default_answer_prompt(query=query, context=context, item_name=item_name)
            try:
                resp = _call_with_timeout(lambda: gen_llm.invoke(prompt), args.llm_timeout)
                answer = getattr(resp, "content", resp) or ""
                generation = _call_with_timeout(
                    lambda: scorer.score(query=query, context=context, answer=answer, reference=reference),
                    args.llm_timeout,
                )
            except Exception as e:  # noqa: BLE001 —— 生成/judge 为外部 I/O，异常/超时该条标 skipped 不伪造
                print(f"[e2e] {qid} 生成/打分异常或超时，跳过：{e}", file=sys.stderr)
                generation = {**{d: None for d in DIMS}, "reasons": {}, "skipped": True, "error": str(e)}

        records.append(
            {
                "qid": qid,
                "query": query,
                "item_name": item_name,
                "tags": tags,
                "retrieval": {"metrics": retrieval_metrics, "retrieved_ids": retrieved_ids, "relevant_ids": relevant_ids},
                "generation": generation,
                # 供 Phase C2 meta-eval 构建人工裁决集（截断存盘，避免膨胀）
                "context": context[:4000],
                "answer": answer[:4000],
                "reference": reference,
                "answer_len": len(answer),
            }
        )
        gen_note = "skipped" if generation.get("skipped") else json.dumps({d: generation.get(d) for d in DIMS}, ensure_ascii=False)
        print(f"[e2e] {idx}/{len(queries)} {qid} 检索 ndcg@10={retrieval_metrics['ndcg@10']} | 生成 {gen_note}")

    # ---------- 聚合（检索层 / 生成层分离） ----------
    retrieval_overall = deps["aggregate_metrics"](retrieval_records)
    retrieval_by_tag = deps["bucket_by_tag"](retrieval_records)
    generation_overall = aggregate_scores([r["generation"] for r in records])
    generation_by_tag = _generation_bucket_summary(records)
    gen_skipped = all(r["generation"].get("skipped") for r in records) if records else True

    # ---------- 输出 ----------
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    run_id = f"{timestamp}_{config_hash}"
    run_dir = out_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    md = _render_report(
        run_id,
        config_hash,
        collection_name,
        str(golden_path),
        len(queries),
        args,
        retrieval_overall,
        retrieval_by_tag,
        generation_overall,
        generation_by_tag,
        gen_skipped,
        gen_skip_reason or "无有效生成样本",
    )
    with open(run_dir / REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(md)

    with open(run_dir / PER_QUERY_FILE, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    with open(run_dir / METRICS_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "run_id": run_id,
                "timestamp": timestamp,
                "config_hash": config_hash,
                "collection": collection_name,
                "golden": str(golden_path),
                "scorer": args.scorer,
                "sample_size": len(records),
                "retrieval": {"overall": retrieval_overall, "by_tag": retrieval_by_tag},
                "generation": {"overall": generation_overall, "by_tag": generation_by_tag, "skipped": gen_skipped},
                "note": "检索层/生成层归因分离；单桶<15 仅定性；数字全实测，缺值/skip 不伪造。",
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
        f.write("\n")

    print(f"\n[e2e] 完成：{run_dir}")
    print(f"[e2e] 检索层 overall = {json.dumps(retrieval_overall, ensure_ascii=False)}")
    if gen_skipped:
        print(f"[e2e] 生成层：skipped（{gen_skip_reason or '无有效样本'}）")
    else:
        print(f"[e2e] 生成层 overall = {json.dumps(generation_overall, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
