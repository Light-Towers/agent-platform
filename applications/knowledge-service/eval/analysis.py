# -*- coding: utf-8 -*-
"""
评测分析编排（数据源边际贡献归因）：把 agent-core 统计原语组织成"贡献矩阵行"。

与 eval/ablation.py 的分工：
- ablation.py = **纯选择/聚合**（通道挑选、指标均值），零外部依赖，供 --help 与单测；
- 本模块 = **跨配置配对分析**（bootstrap 显著性 + 方向判定），依赖 agent_core.metrics.compare。

两个归因方向（回答"这个数据源/这路到底帮没帮上忙"）：
- leave_one_out：base=完整融合（如 rrf_all），每个 variant 去掉一路 →
  贡献 = mean(base - variant)：正且显著 → 被去掉的那路有正贡献（去掉变差）；
  负且显著 → 那路拖后腿（去掉变好）；否则 → 冗余/噪声。
- add_one_in：base=最小集（如 emb_only），每个 variant 叠加一路 →
  增益 = mean(variant - base)：正且显著 → 叠加有增益；负且显著 → 叠加有害；否则中性。

诚实约定：
- 只比较 base 与 variant **都非 skip 且等长**的 query（qid 对齐由调用方保证）；
- 显著性用配对 bootstrap 95% CI（小样本稳健，不假设正态）；CI 含 0 → 判"噪声/中性"，
  绝不把不显著差异渲染成"更优"。
"""

from typing import Any, Dict, List, Optional, Sequence

from agent_core.metrics.compare import bootstrap_mean_diff_ci

# 方向判定标签（报告直接展示）
_VERDICT = {
    "add_one_in": {"pos": "增益", "neg": "有害", "zero": "中性/噪声"},
    "leave_one_out": {"pos": "正贡献(去掉变差)", "neg": "拖后腿(去掉变好)", "zero": "冗余/噪声"},
}


def _direction(mean_diff: float, significant: bool, tol: float) -> str:
    if not significant or abs(mean_diff) <= tol:
        return "zero"
    return "pos" if mean_diff > 0 else "neg"


def contribution_rows(
    base: Dict[str, Sequence[float]],
    variants: Dict[str, Dict[str, Sequence[float]]],
    *,
    mode: str,
    metric_keys: Sequence[str],
    tol: float = 1e-9,
    seed: int = 0,
    n_resamples: int = 2000,
    confidence: float = 0.95,
) -> List[Dict[str, Any]]:
    """
    产出贡献矩阵行（每行 = 一个 variant × 一个 metric 的配对差 + 显著性 + 判定）。

    参数：
        base: {metric_key: per-query 指标序列}——参照集（LOO=完整融合，add=最小集）。
        variants: {label: {metric_key: per-query 指标序列}}——每个变体与 base **按 qid 对齐等长**。
        mode: "leave_one_out" 或 "add_one_in"（决定差值方向与判定文案）。
        metric_keys: 参与比较的指标键（如 ["ndcg@10", "recall@10"]）。
        tol: |mean_diff| <= tol 视为无差异（防浮点噪声误判方向）。
        seed / n_resamples / confidence: 透传 bootstrap（可复现）。
    返回：
        [{label, mode, metric, mean_diff, ci_low, ci_high, significant, verdict}, ...]
        —— 跳过任一侧缺失/长度不等/为空的 (variant, metric)（不伪造）。
    异常：
        ValueError - mode 非法。
    """
    if mode not in _VERDICT:
        raise ValueError(f"未知归因模式：{mode!r}（可选 {list(_VERDICT)}）")
    verdict_map = _VERDICT[mode]
    rows: List[Dict[str, Any]] = []
    for label, vs in variants.items():
        for metric in metric_keys:
            b = list(base.get(metric) or [])
            v = list(vs.get(metric) or [])
            if not b or not v or len(b) != len(v):
                continue  # 缺标注 / 长度不齐 / 空 → 该格不可比，跳过
            if mode == "leave_one_out":
                # 贡献 = 完整 - 去掉该路 = base - variant
                boot = bootstrap_mean_diff_ci(
                    b, v, n_resamples=n_resamples, confidence=confidence, seed=seed
                )
            else:  # add_one_in：增益 = 叠加后 - 基线 = variant - base
                boot = bootstrap_mean_diff_ci(
                    v, b, n_resamples=n_resamples, confidence=confidence, seed=seed
                )
            direction = _direction(boot["mean_diff"], boot["significant"], tol)
            rows.append(
                {
                    "label": label,
                    "mode": mode,
                    "metric": metric,
                    "mean_diff": boot["mean_diff"],
                    "ci_low": boot["ci_low"],
                    "ci_high": boot["ci_high"],
                    "significant": boot["significant"],
                    "n": boot["n"],
                    "verdict": verdict_map[direction],
                }
            )
    return rows


def bucket_slice(
    per_query: List[Dict[str, Any]],
    bucket_key: str,
    bucket_value: Any,
    config: str,
    metric_key: str,
) -> List[float]:
    """
    从 per-query 记录里切出某桶（bucket_key==bucket_value）下某配置某指标的序列（供分桶贡献）。

    per_query 每条：{bucket_key: ..., "configs": {config: {"metrics": {metric: float}, "skipped": bool}}}。
    仅取该桶内、该配置未 skip 且指标存在的 query（qid 对齐由调用方在同序 per_query 上保证）。
    """
    out: List[float] = []
    for rec in per_query:
        if rec.get(bucket_key) != bucket_value:
            continue
        cfg = (rec.get("configs") or {}).get(config)
        if not cfg or cfg.get("skipped"):
            continue
        val = (cfg.get("metrics") or {}).get(metric_key)
        if val is not None:
            out.append(float(val))
    return out


def summarize_rows(rows: List[Dict[str, Any]], metric_key: Optional[str] = None) -> Dict[str, int]:
    """按 verdict 计数概览（快速看"几路正贡献/几路冗余/几路拖后腿"）。"""
    counts = {"增益/正贡献": 0, "有害/拖后腿": 0, "中性/冗余": 0}
    for r in rows:
        if metric_key is not None and r.get("metric") != metric_key:
            continue
        v = r.get("verdict", "")
        if "正贡献" in v or "增益" in v:
            counts["增益/正贡献"] += 1
        elif "拖后腿" in v or "有害" in v:
            counts["有害/拖后腿"] += 1
        else:
            counts["中性/冗余"] += 1
    return counts


__all__ = ["contribution_rows", "bucket_slice", "summarize_rows"]
