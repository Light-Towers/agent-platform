# -*- coding: utf-8 -*-
"""
检索评测指标子包（框架无关，纯 stdlib）。
"""

from agent_core.metrics.compare import (
    average_rank,
    bootstrap_mean_diff_ci,
    cohens_kappa,
    kendall_tau,
    pearson_r,
    spearman_rho,
)
from agent_core.metrics.retrieval import (
    DEFAULT_K,
    Grade,
    Grades,
    compute_retrieval_metrics,
    dcg_at_k,
    hit_rate_at_k,
    mrr,
    ndcg_at_k,
    recall_at_k,
)

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
    "bootstrap_mean_diff_ci",
    "pearson_r",
    "average_rank",
    "spearman_rho",
    "kendall_tau",
    "cohens_kappa",
]
