# -*- coding: utf-8 -*-
"""
Dynamic TopK 消融运行器（M3.5，方案 §6.4）。

功能：
    对 golden 数据集逐条 query，在四种截断策略下各跑一次检索：
        fixed_k=3 / fixed_k=5 / fixed_k=10 / dynamic（线上默认：BGE 重排 + 断崖式动态 TopK）
    并计算对比指标：Recall@10、nDCG@10、**平均返回条数**、**平均上下文 token 估算**、
    检索链路 P95 延迟（ms）。

用法：
    python eval/run_ablation.py --out eval/runs/ [--limit N] [--golden eval/golden_queries.jsonl]
                                [--enable-hyde] [--skip-rerank]

环境要求：
    - 依赖 Milvus 且已运行 import_process 建立索引（与 run_eval.py 相同的环境守卫，
      不可达 / 集合不存在 → 清晰报错并 return 1，不吞异常）。
    - 需要 golden 的 relevant_chunk_ids / grade 按**真实 chunk_id 重新标注**才有意义；
      当前为构造样例（c_xxx 假设标注），实测指标预期全 0，脚本**如实输出并注明原因**，
      不伪造任何数字。

策略口径（诚实声明，文档同步到 eval/topk_ablation.md）：
    - fixed_k=3/5/10：复用 run_eval.retrieve_one 的线上链路（embedding 召回 → RRF 融合 →
      BGE 重排），随后**固定截断前 k 条**——与线上"同一 reranker"的控制变量一致。
      `--skip-rerank` 时退化为 RRF 顺序截断（与 run_eval 的 --skip-rerank 语义对齐）。
    - dynamic：走线上默认链路，断崖式动态 TopK 在 node_rerank 内部执行（本脚本不截断）。
      `--skip-rerank` 时退化为 RRF 顺序全量（≈ fixed_k=10 的退化模式，文档已注明）。
    - **不改动任何线上节点代码**，消融仅在脚本层面切换策略。

输出：
    ``{out}/{timestamp}_{config_hash}/ablation.md`` —— Markdown 对比表 + 统计说明。

诚实声明：本脚本输出的所有数字均为**当次真实检索结果计算值**；在假设性标注 / 未建真实
索引时输出全 0 并注明原因，禁止预填。token 为启发式估算（eval/ablation.estimate_tokens）。

实现说明：重型 import（pymilvus / 检索节点 / run_eval）放在 main() 内延迟加载，
保证 `--help` 在任何环境可打印；实际执行时才触发 Milvus 依赖。
"""

import argparse
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# 脚本直跑路径引导：`python eval/run_ablation.py` 时把项目根加入 sys.path，
# 使 `app.*` 可导入（uv run / 已安装 editable 包时此步为 no-op）。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.conf.milvus_config import milvus_config  # noqa: E402 —— 路径引导后导入，脚本直跑必需
from eval.ablation import (  # noqa: E402 —— 同上
    STRATEGIES,
    aggregate_strategy_rows,
    apply_strategy,
    estimate_tokens,
    extract_doc_text,
)

ABLATION_FILE = "ablation.md"


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="掌柜智库 Dynamic TopK 消融运行器（M3.5）：fixed_k=3/5/10 vs dynamic 对比。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--out", default="eval/runs", help="评测输出根目录")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 条 query（调试用）")
    parser.add_argument("--golden", default="eval/golden_queries.jsonl", help="golden 数据集路径")
    parser.add_argument("--enable-hyde", action="store_true", help="启用 HyDE 召回路（需 LLM）")
    parser.add_argument(
        "--skip-rerank",
        action="store_true",
        help="跳过 BGE 重排（fixed_k 退化为 RRF 顺序截断；dynamic 退化为 RRF 全量 ≈ fixed_k=10）",
    )
    return parser.parse_args(argv)


def _load_retrieval_deps():
    """
    延迟加载检索链路依赖（run_eval / milvus_utils / metrics）。

    说明：这些模块顶部会 import pymilvus / 检索节点等重型依赖；只有真正执行评测
    （Milvus 守卫通过后）才需要，因此放在 main() 内加载，避免 `--help` 也被拖垮。
    """
    from app.clients.milvus_utils import get_milvus_client
    from eval.metrics import compute_retrieval_metrics
    from eval.run_eval import (
        _extract_ids,
        compute_config_hash,
        load_golden_queries,
        retrieve_one,
    )

    return {
        "get_milvus_client": get_milvus_client,
        "compute_retrieval_metrics": compute_retrieval_metrics,
        "extract_ids": _extract_ids,
        "compute_config_hash": compute_config_hash,
        "load_golden_queries": load_golden_queries,
        "retrieve_one": retrieve_one,
    }


def run_strategy(
    retrieve_one,
    strategy: str,
    query: str,
    item_name: str,
    *,
    enable_hyde: bool = False,
    skip_rerank: bool = False,
) -> List[Dict[str, Any]]:
    """
    对单条 query 按消融策略执行检索。

    - dynamic：复用线上默认链路（node_rerank 动态断崖 TopK），本层不截断；
    - fixed_k=N：复用线上链路（embedding → RRF → rerank）后固定截断前 N 条；
      skip_rerank=True 时复用 RRF 顺序截断。
    """
    docs = retrieve_one(query, item_name, enable_hyde=enable_hyde, skip_rerank=skip_rerank)
    return apply_strategy(strategy, docs)


def render_ablation_md(
    run_id: str,
    config_hash: str,
    collection: str,
    sample_size: int,
    rows: List[Dict[str, Any]],
    *,
    skip_rerank: bool,
    any_docs: bool,
    token_estimable: bool,
    metrics_zero_reason: str,
) -> str:
    """生成消融对比 Markdown（数字全部为当次实测，禁止预填）。"""
    lines = [
        "# Dynamic TopK 消融实验报告（M3.5，方案 §6.4）",
        "",
        f"- run_id: `{run_id}`",
        f"- config_hash: `{config_hash}`",
        f"- collection: `{collection}`",
        f"- sample_size: {sample_size}",
        f"- skip_rerank: {skip_rerank}（True 时 fixed_k 为 RRF 顺序截断 / dynamic 为 RRF 全量退化模式）",
        "",
        "## 结果表（由 run_ablation.py 当次实测计算，禁止人工预填）",
        "",
        "| 策略 | Recall@10 | nDCG@10 | 平均返回条数 | 平均上下文 token | P95 延迟(ms) |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['strategy']} | {row['recall@10']} | {row['ndcg@10']} | "
            f"{row['avg_returned']} | {row['avg_tokens']} | {row['p95_latency_ms']} |"
        )
    lines += [
        "",
        "## 统计口径说明",
        "",
        f"- **指标全 0 原因**：{metrics_zero_reason}",
        f"- **平均上下文 token**：启发式估算（CJK 1 token/字符，其余 4 字符/token，见 "
        f"`eval/ablation.estimate_tokens`）；{'可估算' if token_estimable else '无法估算（检索结果无 text/content 字段）'}。",
        "- **P95 延迟**：检索链路（召回→RRF→重排）单 query 耗时，**不含 LLM 生成**；"
        "端到端延迟需在含生成链路中另行压测（方案 §6.4 中该列为端到端口径，本脚本仅覆盖检索段）。",
        f"- **检索结果**：{'存在真实召回结果' if any_docs else '当前无真实召回（未建真实索引 / golden 为假设性标注），所有指标为 0 属预期'}。",
        "",
        "## 判定方法（拿到真实数据后填写）",
        "",
        "1. 比较 fixed_k=10 与 dynamic 的 Recall@10：动态 TopK 的目标**不是提升 Recall**，",
        "   而是「在 Recall 几乎不掉的前提下减少注入 LLM 的无关上下文」。",
        "2. 看 dynamic 的**平均返回条数 / 平均 token** 是否显著低于 fixed_k=10，同时 Recall 损失可接受。",
        "3. 结论写进 `docs/adr/0003-dynamic-topk-threshold.md`（Status: Proposed → Accepted）。",
        "",
    ]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    deps = _load_retrieval_deps()
    get_milvus_client = deps["get_milvus_client"]
    compute_retrieval_metrics = deps["compute_retrieval_metrics"]
    extract_ids = deps["extract_ids"]
    compute_config_hash = deps["compute_config_hash"]
    load_golden_queries = deps["load_golden_queries"]
    retrieve_one = deps["retrieve_one"]

    golden_path = Path(args.golden)
    out_root = Path(args.out)

    # ---------- 环境守卫（与 run_eval.py 一致：Milvus 不可达 / 集合不存在 → return 1） ----------
    collection_name = milvus_config.chunks_collection
    print(f"[ablation] 目标集合：{collection_name}")
    client = get_milvus_client()
    if client is None:
        print(
            f"错误：无法连接 Milvus（{milvus_config.milvus_url}）。请先启动 Milvus 并确认 MILVUS_URL 配置。",
            file=sys.stderr,
        )
        return 1
    if not client.has_collection(collection_name=collection_name):
        print(
            f"错误：Milvus 集合 {collection_name} 不存在。请先运行 import_process 建立索引后再执行消融。",
            file=sys.stderr,
        )
        return 1

    # ---------- 加载 golden ----------
    queries = load_golden_queries(golden_path)
    if args.limit is not None:
        queries = queries[: args.limit]
    if not queries:
        print(f"错误：golden 数据集 {golden_path} 无有效 query。", file=sys.stderr)
        return 1
    print(f"[ablation] 加载 {len(queries)} 条 golden query（来源：{golden_path}）")

    # ---------- 逐条 × 逐策略执行 ----------
    config_hash = compute_config_hash()
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    run_id = f"{timestamp}_{config_hash}"
    run_dir = out_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    per_strategy: Dict[str, List[Dict[str, Any]]] = {s: [] for s in STRATEGIES}
    any_docs = False
    token_estimable = False

    for idx, item in enumerate(queries, start=1):
        qid = item.get("qid", f"q{idx:03d}")
        query = item.get("query", "")
        item_name = item.get("item_name", "")
        relevant_ids = [str(x) for x in (item.get("relevant_chunk_ids") or [])]
        grades = item.get("grade") or {}

        for strategy in STRATEGIES:
            t0 = time.perf_counter()
            try:
                docs = run_strategy(
                    retrieve_one,
                    strategy,
                    query,
                    item_name,
                    enable_hyde=args.enable_hyde,
                    skip_rerank=args.skip_rerank,
                )
            except Exception as e:  # noqa: BLE001 —— 单条失败显式暴露（不吞），便于定位
                print(f"[ablation] {qid} {strategy} 检索链路异常：{e}", file=sys.stderr)
                raise
            latency_ms = (time.perf_counter() - t0) * 1000.0

            retrieved_ids = extract_ids(docs)
            metrics = compute_retrieval_metrics(retrieved_ids, relevant_ids, grades)
            doc_texts = [extract_doc_text(d) for d in docs]
            if docs:
                any_docs = True
            if any(t for t in doc_texts):
                token_estimable = True
            per_strategy[strategy].append(
                {
                    "qid": qid,
                    "strategy": strategy,
                    "retrieved_ids": retrieved_ids,
                    "relevant_ids": relevant_ids,
                    "metrics": metrics,
                    "returned": len(docs),
                    "tokens_estimate": _mean_or_zero([estimate_tokens(t) for t in doc_texts]),
                    "latency_ms": latency_ms,
                }
            )
        print(f"[ablation] {idx}/{len(queries)} {qid} 完成（4 策略）")

    # ---------- 聚合 + 生成报告 ----------
    rows = aggregate_strategy_rows(per_strategy)
    metrics_zero_reason = (
        "golden 数据集 relevant_chunk_ids 为构造样例（c_xxx 假设标注），且当前未接入真实索引，"
        "检索结果为空或无法命中假设 chunk_id，故指标为 0；待真实文档入库并重新标注后即为真实对比。"
    )
    md = render_ablation_md(
        run_id,
        config_hash,
        collection_name,
        len(queries),
        rows,
        skip_rerank=args.skip_rerank,
        any_docs=any_docs,
        token_estimable=token_estimable,
        metrics_zero_reason=metrics_zero_reason,
    )
    report_path = run_dir / ABLATION_FILE
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"\n[ablation] 完成：{report_path}")
    for row in rows:
        print(
            f"[ablation] {row['strategy']}: recall@10={row['recall@10']} "
            f"ndcg@10={row['ndcg@10']} avg_returned={row['avg_returned']} "
            f"avg_tokens={row['avg_tokens']} p95_ms={row['p95_latency_ms']}"
        )
    return 0


def _mean_or_zero(values: List[float]) -> float:
    """均值；空列表返回 0.0。"""
    return sum(values) / len(values) if values else 0.0


if __name__ == "__main__":
    sys.exit(main())
