"""Memory 召回相似度工具。

当前用 bigram Jaccard 相似度（纯 Python，不依赖外部资源），
比子串匹配（`query in content`）更适合中文——
"分析招商" 能匹配 "招商分析"（bigram 集合有交集），子串匹配则不能。

召回评分用 Generative Agents 论文的三因子加权：
    score = alpha * recency + beta * importance + gamma * relevance

生产环境可替换为 embedding + 余弦相似度（需向量模型 + pgvector）。
"""

from __future__ import annotations

import time


def bigrams(text: str) -> set[str]:
    """提取字符级 bigram 集合。"""
    if len(text) < 2:
        return {text} if text else set()
    return {text[i : i + 2] for i in range(len(text) - 1)}


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    """两个集合的 Jaccard 相似度。"""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def text_similarity(query: str, content: str) -> float:
    """两个文本的 bigram Jaccard 相似度。"""
    return jaccard_similarity(bigrams(query.lower()), bigrams(content.lower()))


def recency_score(created_at: float, now: float | None = None, decay: float = 0.995) -> float:
    """时间衰减得分：decay^(now - created_at)。

    decay=0.995 意味着每秒衰减 0.5%，
    约 138 秒后衰减到 0.5，约 920 秒后衰减到 0.01。
    生产环境可调 decay 控制衰减速率。
    """
    if now is None:
        now = time.time()
    age = max(0.0, now - created_at)
    return decay**age


def three_factor_score(
    relevance: float,
    importance: float,
    created_at: float,
    *,
    now: float | None = None,
    decay: float = 0.995,
    alpha: float = 0.3,
    beta: float = 0.4,
    gamma: float = 0.3,
) -> float:
    """三因子加权评分：alpha*recency + beta*importance + gamma*relevance。

    alpha + beta + gamma 应归一化（=1），否则评分可能 >1。
    默认 alpha=0.3 (recency), beta=0.4 (importance), gamma=0.3 (relevance)。
    """
    recency = recency_score(created_at, now, decay)
    return alpha * recency + beta * importance + gamma * relevance


__all__ = [
    "bigrams",
    "jaccard_similarity",
    "text_similarity",
    "recency_score",
    "three_factor_score",
]
