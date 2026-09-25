"""Embedding 向量召回：替换 bigram Jaccard 的语义召回。

需要 embedding 模型（如 OpenAI embedding API）。
无模型时退化为 hash 向量（mock embedding）或 bigram Jaccard。
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Awaitable, Callable

from agent_runtime.memory_recall import text_similarity


class EmbeddingRecall:
    """embedding 向量召回。

    用法：
    ```
    # 有 embedding 模型
    recall = EmbeddingRecall(embed_fn=my_embed_function)
    sim = await recall.similarity("招商分析", "招商引资分析")

    # 无模型 → 退化为 bigram Jaccard
    recall = EmbeddingRecall()
    sim = await recall.similarity("招商分析", "招商引资分析")
    ```
    """

    def __init__(
        self,
        embed_fn: Callable[[str], Awaitable[list[float]]] | None = None,
        dim: int = 128,
    ) -> None:
        self._embed_fn = embed_fn
        self._dim = dim
        self._cache: dict[str, list[float]] = {}

    async def embed(self, text: str) -> list[float]:
        """生成 embedding 向量。"""
        if text in self._cache:
            return self._cache[text]

        if self._embed_fn is not None:
            vec = await self._embed_fn(text)
        else:
            vec = self._hash_embed(text)

        self._cache[text] = vec
        return vec

    def _hash_embed(self, text: str) -> list[float]:
        """无 embedding 模型时用 hash 向量做 mock。"""
        vec = [0.0] * self._dim
        for i in range(0, len(text), 2):
            bigram = text[i : i + 2]
            h = int(hashlib.md5(bigram.encode()).hexdigest(), 16)
            idx = h % self._dim
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    async def similarity(self, query: str, content: str) -> float:
        """两个文本的相似度。"""
        if self._embed_fn is None:
            return text_similarity(query, content)

        q_vec = await self.embed(query)
        c_vec = await self.embed(content)
        return self._cosine(q_vec, c_vec)

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        """余弦相似度。"""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


__all__ = ["EmbeddingRecall"]
