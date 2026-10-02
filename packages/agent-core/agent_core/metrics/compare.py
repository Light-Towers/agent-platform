# -*- coding: utf-8 -*-
"""
评测对比统计原语（纯 stdlib，零依赖，可独立单测）。

服务于 RAG 可持续评测体系的三类"跨配置 / 跨打分器"判定，全部为确定性纯函数：

1. ``bootstrap_mean_diff_ci``：配对 bootstrap 置信区间 + 显著性——判断"改动
   （加数据源 / 调参数）后指标是真提升还是样本噪声"。小样本下比 t 检验稳健
   （不假设正态），符合"单桶样本可能 <15"的现实。
2. ``spearman_rho`` / ``kendall_tau``：秩相关——衡量自动打分器与人工判定的排序
   一致性，是"端到端评测框架选型"的主判据之一。
3. ``cohens_kappa``：分箱后标签一致性——对系统性偏移不敏感，补秩相关之不足。

约定（防"把无法判定伪装成判定为显著"）：
- 成对输入要求等长；空输入或退化（常数序列 / 无变异）返回中性值（0.0）而非抛错，
  由调用方结合样本量判读。
- 所有随机过程接受 ``seed``，保证可复现（同一 bootstrap 输入 → 同一 CI）。
- 框架无关：仅 stdlib，不 import 任何宿主应用或第三方包。
"""

import math
import random
from typing import Any, Dict, List, Sequence, Union

Number = Union[int, float]


def _require_paired(a: Sequence[Number], b: Sequence[Number]) -> List[float]:
    """校验成对序列等长并返回逐对差值序列（a_i - b_i）。长度不等 → ValueError。"""
    la, lb = len(a), len(b)
    if la != lb:
        raise ValueError(f"成对比较要求等长，实际 len(a)={la} len(b)={lb}")
    return [float(a[i]) - float(b[i]) for i in range(la)]


def bootstrap_mean_diff_ci(
    a: Sequence[Number],
    b: Sequence[Number],
    *,
    n_resamples: int = 2000,
    confidence: float = 0.95,
    seed: int = 0,
) -> Dict[str, Any]:
    """
    配对 bootstrap：估计 ``mean(a - b)`` 的置信区间与显著性。

    参数：
        a, b: 同一批 query 上两个配置（candidate / baseline）的指标序列（等长、按 qid 对齐）。
        n_resamples: 重采样次数（默认 2000）。
        confidence: 置信水平（默认 0.95）。
        seed: 随机种子（默认 0，保证可复现）。
    返回：
        {
          "mean_diff": float,     # 点估计 = mean(a-b)
          "ci_low": float, "ci_high": float,   # 百分位 bootstrap 区间
          "significant": bool,    # 区间是否不含 0（正/负显著方向由 mean_diff 符号给出）
          "n": int,
        }
        空输入 → mean_diff=0, ci=[0,0], significant=False, n=0。
    """
    diffs = _require_paired(a, b)
    n = len(diffs)
    mean_diff = sum(diffs) / n if n else 0.0
    if n == 0 or n_resamples <= 0:
        return {"mean_diff": round(mean_diff, 6), "ci_low": 0.0, "ci_high": 0.0, "significant": False, "n": n}

    rng = random.Random(seed)
    means: List[float] = []
    for _ in range(n_resamples):
        sample = [diffs[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()

    alpha = max(0.0, min(1.0, 1.0 - confidence))
    lo_idx = int(math.floor((alpha / 2.0) * n_resamples))
    hi_idx = int(math.ceil((1.0 - alpha / 2.0) * n_resamples)) - 1
    lo_idx = max(0, min(lo_idx, n_resamples - 1))
    hi_idx = max(0, min(hi_idx, n_resamples - 1))
    ci_low, ci_high = means[lo_idx], means[hi_idx]
    significant = ci_low > 0.0 or ci_high < 0.0  # 区间整体在 0 的一侧 → 显著
    return {
        "mean_diff": round(mean_diff, 6),
        "ci_low": round(ci_low, 6),
        "ci_high": round(ci_high, 6),
        "significant": bool(significant),
        "n": n,
    }


def pearson_r(x: Sequence[Number], y: Sequence[Number]) -> float:
    """Pearson 相关系数（内部用于 Spearman）；退化（任一序列无变异）返回 0.0。"""
    diffs = _require_paired(x, y)  # 仅用于长度校验
    n = len(diffs)
    if n < 2:
        return 0.0
    mx = sum(x) / n
    my = sum(y) / n
    cov = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    vx = sum((v - mx) ** 2 for v in x)
    vy = sum((v - my) ** 2 for v in y)
    if vx <= 0 or vy <= 0:
        return 0.0
    return cov / math.sqrt(vx * vy)


def average_rank(values: Sequence[Number]) -> List[float]:
    """返回每个元素的名次（升序），并列取平均秩（mid-rank），供 Spearman 使用。"""
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        # 并列块 order[i..j] 占据名次 i+1 .. j+1，平均 = (i+1 + j+1)/2
        avg = (i + 1 + j + 1) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman_rho(x: Sequence[Number], y: Sequence[Number]) -> float:
    """
    Spearman 秩相关 ρ：对两组打分先转平均秩，再算 Pearson。

    用于"自动打分 vs 人工打分"排序一致性（主判据）。退化返回 0.0。
    """
    rx = average_rank(x)
    ry = average_rank(y)
    return pearson_r(rx, ry)


def kendall_tau(x: Sequence[Number], y: Sequence[Number]) -> float:
    """
    Kendall τ-b 秩相关：处理并列（ties）的一致性度量。

    τ-b = (C - D) / sqrt((n0 - n1)(n0 - n2))，C/D 为一致/不一致对数，
    n1/n2 为 x/y 的并列对数。分母为 0（完全并列）返回 0.0。
    比 τ-a 更适合成对打分（打分值常重复）。
    """
    n = len(x)
    _require_paired(x, y)
    if n < 2:
        return 0.0
    concordant = discordant = ties_x = ties_y = 0
    for i in range(n):
        for j in range(i + 1, n):
            dx = x[i] - x[j]
            dy = y[i] - y[j]
            if dx == 0 and dy == 0:
                ties_x += 1
                ties_y += 1
            elif dx == 0:
                ties_x += 1
            elif dy == 0:
                ties_y += 1
            elif (dx > 0) == (dy > 0):
                concordant += 1
            else:
                discordant += 1
    n0 = n * (n - 1) / 2.0
    denom = math.sqrt((n0 - ties_x) * (n0 - ties_y))
    if denom <= 0:
        return 0.0
    return (concordant - discordant) / denom


def cohens_kappa(x: Sequence[Any], y: Sequence[Any]) -> float:
    """
    Cohen's κ：两组**离散标签**的一致性（观察一致率 vs 偶然一致率）。

    用于分箱后的 judge-vs-human 标签一致性（对系统性偏移不敏感）。
    要求等长；单类别或完全偶然时返回 0.0（无法区分优劣）。
    """
    if len(x) != len(y):
        raise ValueError(f"成对比较要求等长，实际 len(x)={len(x)} len(y)={len(y)}")
    n = len(x)
    if n == 0:
        return 0.0
    labels = set(x) | set(y)
    po = sum(1 for i in range(n) if x[i] == y[i]) / n
    pe = 0.0
    for lab in labels:
        px = sum(1 for v in x if v == lab) / n
        py = sum(1 for v in y if v == lab) / n
        pe += px * py
    if pe >= 1.0:
        return 0.0
    return (po - pe) / (1.0 - pe)


__all__ = [
    "bootstrap_mean_diff_ci",
    "pearson_r",
    "average_rank",
    "spearman_rho",
    "kendall_tau",
    "cohens_kappa",
]
