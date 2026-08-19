# -*- coding: utf-8 -*-
"""
消融实验纯函数（M3.5，方案 §6.4）：策略解析 / 截断 / token 估算 / 统计。

设计说明：
- 本模块**零外部依赖**（仅 stdlib），供 `eval/run_ablation.py` 与单测复用，
  保证消融策略切换逻辑可以在不连 Milvus 的情况下独立验证。
- token 估算为**粗略启发式**，用于「平均注入 LLM 的上下文 token」对比；
  **禁止用本函数预填任何实验数字**，它只产出估算逻辑，数值由真实检索结果计算。
"""

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

# 消融策略清单（方案 §6.4 自变量）
STRATEGIES: Tuple[str, ...] = ("fixed_k=3", "fixed_k=5", "fixed_k=10", "dynamic")


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
