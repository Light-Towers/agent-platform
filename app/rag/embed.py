"""Embedding 客户端：OpenAI 兼容 /embeddings；无密钥时走确定性 mock。

mock 模式（EMBEDDING_MODE=mock 或 auto 且无密钥）基于内容哈希生成固定向量，
保证开发/测试链路可跑通；语义相似度无意义，检索质量由 BM25 分支兜底。
"""

import hashlib
import math

import httpx

from app.config import get_settings


def _mock_embed(text: str, dim: int) -> list[float]:
    vec = []
    counter = 0
    while len(vec) < dim:
        digest = hashlib.sha256(f"{text}:{counter}".encode("utf-8")).digest()
        vec.extend(b / 255.0 - 0.5 for b in digest)
        counter += 1
    vec = vec[:dim]
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _use_remote(settings) -> bool:
    if settings.embedding_mode == "mock":
        return False
    if settings.embedding_mode == "remote":
        return True
    return bool(settings.embedding_api_key)


async def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    settings = get_settings()
    if not _use_remote(settings):
        return [_mock_embed(t, settings.vector_dim) for t in texts]

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{settings.embedding_base_url.rstrip('/')}/embeddings",
            headers={"Authorization": f"Bearer {settings.embedding_api_key}"},
            json={"model": settings.embedding_model, "input": texts},
        )
        resp.raise_for_status()
        data = sorted(resp.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]


async def embed_query(text: str) -> list[float]:
    return (await embed_texts([text]))[0]
