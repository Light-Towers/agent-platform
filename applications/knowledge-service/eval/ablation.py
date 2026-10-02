# -*- coding: utf-8 -*-
"""
消融实验纯函数（M3.5 方案 §6.4 TopK 消融 + 路线消融）：
策略解析 / 截断 / token 估算 / 统计 / 路线选择。

设计说明：
- 本模块**零外部依赖**（仅 stdlib），供 `eval/run_ablation.py`、`eval/run_route_ablation.py`
  与单测复用，保证消融策略/路线切换逻辑可以在不连 Milvus 的情况下独立验证。
- token 估算为**粗略启发式**，用于「平均注入 LLM 的上下文 token」对比；
  **禁止用本函数预填任何实验数字**，它只产出估算逻辑，数值由真实检索结果计算。
- 路线消融（route_*）：把「哪些召回通道参与 RRF 融合」与「embedding 内 dense/sparse 配比」
  抽象为纯选择逻辑，运行器只负责喂真实检索列表，聚合口径与 TopK 消融一致。
"""

import hashlib
import math
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

# 消融策略清单（方案 §6.4 自变量）
STRATEGIES: Tuple[str, ...] = ("fixed_k=3", "fixed_k=5", "fixed_k=10", "dynamic")

# ---------------------------------------------------------------------------
# 路线消融常量（方案：RRF 混合排名 vs 单路召回）
# ---------------------------------------------------------------------------
# 层 1：RRF 通道层——每个配置声明「参与融合的具名通道」。单路配置只含一路
# （喂进 RRF 不改变单列表顺序，仅用于统一截断口径）；rrf_* 为多路融合。
ROUTE_CONFIGS: Dict[str, Tuple[str, ...]] = {
    "emb_only": ("embedding",),
    "hyde_only": ("hyde",),
    "kg_only": ("kg",),
    "rrf_emb_hyde": ("embedding", "hyde"),
    "rrf_all": ("embedding", "hyde", "kg"),
}
# 报告固定行序（缺失通道由运行器标注 skipped）。
ROUTE_ORDER: Tuple[str, ...] = (
    "emb_only",
    "hyde_only",
    "kg_only",
    "rrf_emb_hyde",
    "rrf_all",
)

# 层 2：embedding 内 dense/sparse 向量级配比扫描。
# (label, (dense_weight, sparse_weight))；dense_only/sparse_only/dense+sparse 为对照，
# 其余为 ranker_weights 扫描档位（供回填 retrieval.yaml 选最优配比）。
LEXICAL_WEIGHT_SCAN: Tuple[Tuple[str, Tuple[float, float]], ...] = (
    ("dense_only", (1.0, 0.0)),
    ("w_0.8_0.2", (0.8, 0.2)),
    ("w_0.5_0.5", (0.5, 0.5)),
    ("w_0.2_0.8", (0.2, 0.8)),
    ("sparse_only", (0.0, 1.0)),
)
# dense+sparse 线上默认档（等同 w_0.8_0.2，单列便于报告对照命名）。
HYBRID_DEFAULT_LABEL = "dense+sparse"

# 路线消融专用集合名（合成语料 seed 与 run_route_ablation 共用）。
# 与生产集合隔离，避免 node_import_milvus 的「同 item_name 幂等清理」误删真实语料；
# seed_synthetic_corpus.py / run_route_ablation.py 在未显式设置 CHUNKS_COLLECTION 时
# 以此 setdefault 环境变量（knowledge_service 导入前生效）。
EVAL_COLLECTION_NAME = "eval_rag_routes"


def fallback_config_hash() -> str:
    """
    部署镜像落后于工作树、缺 ``knowledge_service.conf.config_hash`` 时的降级实现（纯 stdlib）。

    仅用于**实验归因标签 / run_id 目录名**，不参与任何检索数值计算（recall/mrr/ndcg 不受影响）。
    基于影响实验可复现性的关键环境变量做 sha256 短哈希，输出形状与 compute_config_hash 一致。
    """
    raw = "|".join(
        [
            os.environ.get("CHUNKS_COLLECTION", ""),
            os.environ.get("EMBEDDING_MODE", ""),
        ]
    )
    return "fb" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]


def select_channels(
    routes: Dict[str, Sequence[Any]],
    channels: Sequence[str],
    weights: Optional[Dict[str, float]] = None,
) -> List[Tuple[List[Any], float]]:
    """
    按**显式通道名序列**挑选参与 RRF 的 source 列表（纯函数，零依赖）。

    这是 select_route_sources 的底层原语，也是边际贡献（leave-one-out / add-one-in）
    动态派生任意子集融合的入口——无需把每个子集都写进 ROUTE_CONFIGS。

    参数：
        routes: {channel: 该通道检索结果 list}。
        channels: 参与融合的通道名序列（顺序不影响 RRF 结果，权重才影响）。
        weights: {channel: RRF 权重}；缺省通道按 1.0（与 node_rrf 兜底口径一致）。
    返回：
        [(channel_docs, weight), ...] —— 仅包含 channels 声明且 routes 中**非空**的通道。
    """
    weights = weights or {}
    sources: List[Tuple[List[Any], float]] = []
    for channel in channels:
        docs = list(routes.get(channel) or [])
        if not docs:
            continue
        sources.append((docs, float(weights.get(channel, 1.0))))
    return sources


def select_route_sources(
    routes: Dict[str, Sequence[Any]],
    config: str,
    weights: Optional[Dict[str, float]] = None,
) -> List[Tuple[List[Any], float]]:
    """
    按路线配置挑选参与 RRF 的 source 列表（纯函数，零依赖）。

    参数：
        routes: {channel: 该通道检索结果 list}，channel ∈ {embedding, hyde, kg}。
        config: ROUTE_CONFIGS 的键（如 "rrf_all" / "emb_only"）。
        weights: {channel: RRF 权重}；缺省通道按 1.0（与 node_rrf 兜底口径一致）。
    返回：
        [(channel_docs, weight), ...] —— 仅包含 config 声明且 routes 中**非空**的通道，
        可直接喂给 `reciprocal_rank_fusion`。空通道被剔除（运行器据此标注 skipped）。
    异常：
        ValueError - 未知 config。
    """
    if config not in ROUTE_CONFIGS:
        raise ValueError(f"未知路线配置：{config!r}（可选 {tuple(ROUTE_CONFIGS)}）")
    return select_channels(routes, ROUTE_CONFIGS[config], weights)


def leave_one_out_configs(base_config: str = "rrf_all") -> Dict[str, Tuple[str, ...]]:
    """
    枚举 base_config 的 leave-one-out 变体：逐一去掉一个通道得到的通道子集。

    用于数据源**净贡献**归因：LOO(X) 相对 base 的指标差即通道 X 的边际贡献
    （去掉 X 掉分 → X 有正贡献；去掉 X 涨分 → X 拖后腿；不变 → X 冗余）。

    返回：{label: channels}，label 形如 "loo:kg"（= base 去 kg）。
    异常：ValueError - 未知 base_config。
    """
    if base_config not in ROUTE_CONFIGS:
        raise ValueError(f"未知路线配置：{base_config!r}（可选 {tuple(ROUTE_CONFIGS)}）")
    base_channels = ROUTE_CONFIGS[base_config]
    out: Dict[str, Tuple[str, ...]] = {}
    for ch in base_channels:
        out[f"loo:{ch}"] = tuple(c for c in base_channels if c != ch)
    return out


def active_route_channels(routes: Dict[str, Sequence[Any]], config: str) -> Tuple[str, ...]:
    """
    返回某配置下**实际有候选**的通道（用于判定该配置是否可测 / 需 skip）。

    异常：
        ValueError - 未知 config。
    """
    if config not in ROUTE_CONFIGS:
        raise ValueError(f"未知路线配置：{config!r}（可选 {tuple(ROUTE_CONFIGS)}）")
    return tuple(ch for ch in ROUTE_CONFIGS[config] if list(routes.get(ch) or []))


def parse_strategy(strategy: str) -> Tuple[str, Optional[int]]:
    """
    解析消融策略名。

    返回：
        ("fixed", k) 或 ("dynamic", None)。
    异常：
        ValueError - 未知策略名 / fixed_k 非正整数。
    """
    s = (strategy or "").strip().lower()
    if s == "dynamic":
        return "dynamic", None
    if s.startswith("fixed_k="):
        raw = s.split("=", 1)[1].strip()
        try:
            k = int(raw)
        except ValueError:
            raise ValueError(f"无效 fixed_k 策略：{strategy!r}（应为 fixed_k=<正整数>，可选 {STRATEGIES}）") from None
        if k <= 0:
            raise ValueError(f"无效 fixed_k 策略：{strategy!r}（k 必须为正整数）")
        return "fixed", k
    raise ValueError(f"未知消融策略：{strategy!r}（可选 {STRATEGIES}）")


def truncate_to_fixed_k(docs: Sequence[Any], k: int) -> List[Any]:
    """固定截断：取前 k 条（k 超过长度时返回全部）。"""
    if k <= 0:
        return []
    return list((docs or [])[:k])


def apply_strategy(strategy: str, docs: Sequence[Any]) -> List[Any]:
    """
    对已检索结果应用消融策略（纯函数）。

    - dynamic：原样返回（断崖式动态 TopK 在 node_rerank 内部执行，本层不截断）；
    - fixed_k=N：固定取前 N 条。
    """
    kind, k = parse_strategy(strategy)
    if kind == "fixed":
        return truncate_to_fixed_k(docs, k)
    return list(docs or [])


def extract_doc_text(doc: Any) -> str:
    """
    从检索结果 dict 提取可用于 token 估算的文本。

    兼容两种节点输出结构：
    - node_rerank 的 reranked_docs：字段为 ``text``；
    - RRF 直接输出（--skip-rerank）：字段为 ``content``。
    两者都缺失时返回空串（该条贡献 0 token）。
    """
    if not isinstance(doc, dict):
        return ""
    return str(doc.get("text") or doc.get("content") or "")


def estimate_tokens(text: str) -> int:
    """
    轻量 token 估算（粗略启发式，非精确分词）：
    - CJK 字符按 1 token / 字符（中文 tokenizer 近似）；
    - 其余字符按 4 字符 / token（英文/数字近似）。
    返回至少 1（非空文本），空文本返回 0。
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return max(1, int(cjk + other / 4))


def compute_mean(values: Sequence[float]) -> float:
    """列表均值；空列表返回 0.0。"""
    if not values:
        return 0.0
    return sum(values) / len(values)


def compute_p95(values: Sequence[float]) -> float:
    """
    计算 P95（百分位 95）。空列表返回 0.0。
    口径：升序排序后取 ceil(0.95 * n) - 1 位置的元素（含 n=1 时返回唯一值）。
    """
    sorted_vals = sorted(values or [])
    if not sorted_vals:
        return 0.0
    n = len(sorted_vals)
    idx = max(0, int(math.ceil(0.95 * n)) - 1)
    idx = min(idx, n - 1)
    return float(sorted_vals[idx])


def aggregate_strategy_rows(per_query: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    按策略聚合消融指标（均值 / P95）。

    输入：
        per_query: {strategy: [ {metrics, returned, tokens_estimate, latency_ms}, ... ]}
    返回：
        每策略一行：strategy / recall@10 / ndcg@10 / avg_returned / avg_tokens / p95_latency_ms。
    """
    rows = []
    for strategy in STRATEGIES:
        recs = per_query.get(strategy, [])
        rows.append(
            {
                "strategy": strategy,
                "recall@10": round(compute_mean([r["metrics"]["recall@10"] for r in recs]), 4),
                "ndcg@10": round(compute_mean([r["metrics"]["ndcg@10"] for r in recs]), 4),
                "avg_returned": round(compute_mean([r["returned"] for r in recs]), 2),
                "avg_tokens": round(compute_mean([r["tokens_estimate"] for r in recs]), 1),
                "p95_latency_ms": round(compute_p95([r["latency_ms"] for r in recs]), 1),
            }
        )
    return rows


# 路线/向量级对比表统一指标列（均值）。
_ROUTE_METRIC_KEYS: Tuple[str, ...] = ("recall@5", "recall@10", "mrr", "hit_rate@5", "ndcg@10")


def aggregate_route_rows(
    per_config: Dict[str, List[Dict[str, Any]]],
    order: Sequence[str],
) -> List[Dict[str, Any]]:
    """
    按路线/向量级配置聚合检索指标（均值），产出一张对比表的行。

    输入：
        per_config: {config: [ {"metrics": {...}, "returned": int, "skipped": bool?}, ... ]}
            —— 每 query 一条记录；某 query 在某配置无可测候选时记 skipped=True。
        order: 固定行序（如 ROUTE_ORDER）。
    返回：
        每配置一行：{config, skipped, sample_size, **_ROUTE_METRIC_KEYS 均值, avg_returned}。
        skipped=True 表示该配置所有 query 均无候选（如缺 KG/LLM），指标不具参考性。
    说明：均值只对**未 skip** 的记录计算，避免空列表把均值拉低成假数据。
    """
    rows: List[Dict[str, Any]] = []
    for config in order:
        recs = per_config.get(config, [])
        active = [r for r in recs if not r.get("skipped")]
        row: Dict[str, Any] = {
            "config": config,
            "skipped": len(active) == 0,
            "sample_size": len(active),
        }
        for key in _ROUTE_METRIC_KEYS:
            row[key] = round(compute_mean([r["metrics"][key] for r in active]), 4)
        row["avg_returned"] = round(compute_mean([r["returned"] for r in active]), 2)
        rows.append(row)
    return rows
