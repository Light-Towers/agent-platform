# -*- coding: utf-8 -*-
"""
兼容 shim：重导出 agent_core.metrics.retrieval 公共 API，保持旧 import 路径
``from eval.metrics import ...`` 不变。

过渡期保留；稳定后调用点应改为 ``from agent_core.metrics.retrieval import ...``。
"""

from agent_core.metrics.retrieval import *  # noqa: F403  —— 重导出，保旧路径
from agent_core.metrics.retrieval import (  # noqa: F401  —— 显式再导出公共名（便于静态分析）
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
