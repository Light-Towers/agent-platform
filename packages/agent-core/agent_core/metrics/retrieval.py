# -*- coding: utf-8 -*-
"""
检索评测指标（纯函数，零外部依赖，可独立单测）。

指标口径与方案 §6.2 保持一致（M2 必跑四类检索指标）：

- ``recall_at_k``：相关块进入 TopK 的比例 = |retrieved@K ∩ relevant| / |relevant|。
- ``hit_rate_at_k``：TopK 内是否至少命中一个相关块（二值）。
- ``mrr``：第一个相关块的排名倒数（无相关块则为 0）。
- ``ndcg_at_k``：基于 ``grade`` 分级（2=高度相关 / 1=部分相关 / 0=不相关）的
  归一化折损累计增益。**二值标注无法算 nDCG**，nDCG 能区分"排序好坏"而不只是"有没有"。

边界约定：
- 空召回列表：recall / hit_rate / mrr / ndcg 一律返回 0.0（不抛异常）。
- 空相关集合：recall / hit_rate 返回 0.0；nDCG 在没有任何 grade>0 时返回 0.0。
- 所有输入 id 统一按 ``str`` 归一化比较，兼容 Milvus int64 主键与字符串 chunk_id。

框架无关：本模块仅依赖 stdlib，不 import 任何宿主应用或第三方包。
"""

import math
from typing import Dict, Iterable, List, Optional, Sequence, Union

# grade 分级：2=高度相关 / 1=部分相关 / 0=不相关
Grade = Union[int, float]
Grades = Dict[Union[str, int], Grade]

DEFAULT_K = 10


def _normalize_ids(ids: Optional[Iterable[Union[str, int]]]) -> List[str]:
    """把任意 id 列表归一化为非空 str 列表（跳过 None）。"""
    if not ids:
        return []
    return [str(x) for x in ids if x is not None]


def _normalize_grades(grades: Optional[Grades]) -> Dict[str, float]:
    """把 grade dict 归一化为 {str(chunk_id): float(grade)}。"""
    if not grades:
        return {}
    out: Dict[str, float] = {}
    for chunk_id, grade in grades.items():
        if chunk_id is None:
            continue
        try:
            out[str(chunk_id)] = float(grade)
        except (TypeError, ValueError):
            continue
    return out


def recall_at_k(retrieved: Sequence[Union[str, int]], relevant: Sequence[Union[str, int]], k: int) -> float:
    """
    计算 Recall@K。

    参数：
        retrieved: 检索返回的 chunk_id 列表（按排名序）
        relevant: 相关 chunk_id 列表（黄金标注）
        k: 截断深度
    返回：
        float - [0,1]；相关集合为空时返回 0.0。
    """
    if k <= 0:
        return 0.0
    ret = set(_normalize_ids(retrieved)[:k])
    rel = set(_normalize_ids(relevant))
    if not rel:
        return 0.0
    return len(ret & rel) / len(rel)


def hit_rate_at_k(retrieved: Sequence[Union[str, int]], relevant: Sequence[Union[str, int]], k: int) -> float:
    """
    计算 HitRate@K（TopK 内是否至少命中一个相关块）。

    参数：
        retrieved: 检索返回的 chunk_id 列表（按排名序）
        relevant: 相关 chunk_id 列表（黄金标注）
        k: 截断深度
    返回：
        float - 1.0 或 0.0；相关集合为空时返回 0.0。
    """
    if k <= 0:
        return 0.0
    ret = set(_normalize_ids(retrieved)[:k])
    rel = set(_normalize_ids(relevant))
    if not rel:
        return 0.0
    return 1.0 if (ret & rel) else 0.0


def mrr(retrieved: Sequence[Union[str, int]], relevant: Sequence[Union[str, int]]) -> float:
    """
    计算 MRR（Mean Reciprocal Rank）：第一个相关块的排名倒数。

    参数：
        retrieved: 检索返回的 chunk_id 列表（按排名序）
        relevant: 相关 chunk_id 列表（黄金标注）
    返回：
        float - [0,1]；无相关块或空召回时返回 0.0。
    """
    ret = _normalize_ids(retrieved)
    rel = set(_normalize_ids(relevant))
    if not rel or not ret:
        return 0.0
    for rank, chunk_id in enumerate(ret, start=1):
        if chunk_id in rel:
            return 1.0 / rank
    return 0.0


def dcg_at_k(relevance_scores: Sequence[float], k: Optional[int] = None) -> float:
    """
    计算 DCG@K（Discounted Cumulative Gain，折损累计增益）。

    公式：DCG@K = Σ_{i=1..K} rel_i / log2(i + 1)（i 从 1 计）。
    rel_i 为第 i 位的分级相关性（grade）。

    参数：
        relevance_scores: 按排名序的 grade 序列（与 retrieved 一一对应）
        k: 截断深度；None 表示全部
    返回：
        float - DCG 值。
    """
    scores = [float(s) for s in (relevance_scores or [])]
    if k is not None:
        scores = scores[: max(0, k)]
    return sum(score / math.log2(idx + 2) for idx, score in enumerate(scores) if score > 0)


def ndcg_at_k(
    retrieved: Sequence[Union[str, int]],
    relevant: Sequence[Union[str, int]],
    grades: Optional[Grades] = None,
    k: int = DEFAULT_K,
) -> float:
    """
    计算 nDCG@K（归一化折损累计增益），利用 grade 分级反映"排序好坏"。

    参数：
        retrieved: 检索返回的 chunk_id 列表（按排名序）
        relevant: 相关 chunk_id 列表（黄金标注；可与 grades 同时提供）
        grades: {chunk_id: grade} 分级相关性，2=高度相关 / 1=部分相关 / 0=不相关；
                缺省视为全部 grade=1（退化为二值，仅作兜底，不推荐）
        k: 截断深度，默认 10
    返回：
        float - [0,1]；idcg 为 0（无任何正分级相关块）时返回 0.0。
    """
    if k <= 0:
        return 0.0
    ret = _normalize_ids(retrieved)[:k]
    grade_map = _normalize_grades(grades)
    rel = set(_normalize_ids(relevant))

    # 没有正分级 → 没有可判定的相关块 → nDCG 无意义，返回 0
    if not any(g > 0 for g in grade_map.values()) and not rel:
        return 0.0

    # 实际 DCG：按检索返回顺序取各 chunk 的 grade
    dcg = dcg_at_k([grade_map.get(cid, 0.0) for cid in ret], k=k)

    # 理想 DCG：所有正分级相关块按 grade 降序排列（即"完美排序"）
    ideal_scores = sorted((g for g in grade_map.values() if g > 0), reverse=True)
    idcg = dcg_at_k(ideal_scores, k=k)
    if idcg <= 0:
        return 0.0
    return dcg / idcg


def compute_retrieval_metrics(
    retrieved: Sequence[Union[str, int]],
    relevant: Sequence[Union[str, int]],
    grades: Optional[Grades] = None,
) -> Dict[str, float]:
    """
    计算一条 query 的完整检索指标集（M2 必跑指标）。

    参数：
        retrieved: 检索返回的 chunk_id 列表（按排名序）
        relevant: 相关 chunk_id 列表（黄金标注）
        grades: {chunk_id: grade} 分级相关性（nDCG 必需）
    返回：
        dict - {"recall@5": float, "recall@10": float, "mrr": float,
                "hit_rate@5": float, "ndcg@10": float}
    """
    return {
        "recall@5": recall_at_k(retrieved, relevant, 5),
        "recall@10": recall_at_k(retrieved, relevant, 10),
        "mrr": mrr(retrieved, relevant),
        "hit_rate@5": hit_rate_at_k(retrieved, relevant, 5),
        "ndcg@10": ndcg_at_k(retrieved, relevant, grades, k=10),
    }


__all__ = [
    "Grade",
    "Grades",
    "DEFAULT_K",
    "recall_at_k",
    "hit_rate_at_k",
    "mrr",
    "dcg_at_k",
    "ndcg_at_k",
    "compute_retrieval_metrics",
]
