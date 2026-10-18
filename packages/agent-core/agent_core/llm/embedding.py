# -*- coding: utf-8 -*-
"""Embedding 客户端：可插拔后端（langchain_openai | langchain_huggingface | sentence_transformers）。

框架无关内核：三个后端均为可选 extra，在 __init__ 中懒导入，模块本身仅依赖 stdlib。
`langchain_openai` 是生产路径（OpenAI 兼容端点）；另两个是本地/离线路径。
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)


class BaseEmbedder(ABC):
    """Embedder 接口。"""

    @abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量嵌入文本。"""

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]:
        """嵌入单条查询。"""


class LangchainOpenAIEmbedder(BaseEmbedder):
    """langchain-openai embedding 生产实现。"""

    def __init__(self, api_key: str, model: str = "text-embedding-3-small", base_url: str = "") -> None:
        from langchain_openai import OpenAIEmbeddings

        kwargs: dict[str, Any] = {"api_key": api_key, "model": model}
        if base_url:
            kwargs["base_url"] = base_url
        self._embedder = OpenAIEmbeddings(**kwargs)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return await self._embedder.aembed_documents(texts)

    async def embed_query(self, text: str) -> list[float]:
        return await self._embedder.aembed_query(text)


class LangchainHuggingfaceEmbedder(BaseEmbedder):
    """langchain-huggingface embedding 可选实现（BGE 权重本地自备）。"""

    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5") -> None:
        from langchain_huggingface import HuggingFaceEmbeddings

        self._embedder = HuggingFaceEmbeddings(model_name=model_name)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return await self._embedder.aembed_documents(texts)

    async def embed_query(self, text: str) -> list[float]:
        return await self._embedder.aembed_query(text)


class SentenceTransformerEmbedder(BaseEmbedder):
    """sentence-transformers 本地推理后端（dev/离线；权重走 HF 缓存）。

    与 `LangchainHuggingfaceEmbedder` 的分工：那个要 `langchain-huggingface` 包
    （当前未装）；本实现只用**已装依赖** `sentence-transformers`，dev/离线环境
    零新增依赖即可跑通全链路（2026-10-18：siliconflow 余额耗尽时用它把 E2E 验过）。

    **BGE 中文系检索约定（模型卡）**：query 侧加指令前缀、document 侧不加。
    两侧必须同源——只加一侧 = 向量空间错位，召回质量**静默**劣化（不报错，
    只是召不准）。故 embed_query 与 embed_texts 的前缀差异是契约，不是 bug。
    """

    #: bge-*-zh v1.5 模型卡指定的 query 指令前缀（document 侧刻意不加）
    _QUERY_PROMPT = "为这个句子生成表示以用于检索相关文章："

    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5", device: str | None = None) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name, device=device)

    def _encode_sync(self, texts: list[str], prompt: str | None) -> list[list[float]]:
        vectors = self._model.encode(texts, prompt=prompt, normalize_embeddings=True)
        return [[float(x) for x in v] for v in vectors]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        # to_thread：encode 是 CPU 密集，别占事件循环（并发查询时互不阻塞）
        return await asyncio.to_thread(self._encode_sync, texts, None)

    async def embed_query(self, text: str) -> list[float]:
        vectors = await asyncio.to_thread(self._encode_sync, [text], self._QUERY_PROMPT)
        return vectors[0]


def build_embedder(backend: str, **kwargs: Any) -> BaseEmbedder:
    """工厂：按 backend 切换。"""
    if backend == "langchain_huggingface":
        return LangchainHuggingfaceEmbedder(model_name=kwargs.get("model", "BAAI/bge-small-zh-v1.5"))
    if backend == "sentence_transformers":
        return SentenceTransformerEmbedder(model_name=kwargs.get("model", "BAAI/bge-small-zh-v1.5"))
    return LangchainOpenAIEmbedder(
        api_key=kwargs.get("api_key", ""),
        model=kwargs.get("model", "text-embedding-3-small"),
        base_url=kwargs.get("base_url", ""),
    )


__all__ = [
    "BaseEmbedder",
    "LangchainOpenAIEmbedder",
    "LangchainHuggingfaceEmbedder",
    "SentenceTransformerEmbedder",
    "build_embedder",
]
