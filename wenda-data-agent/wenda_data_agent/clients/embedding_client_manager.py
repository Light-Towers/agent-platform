"""Embedding 客户端管理：可插拔后端（langchain_openai | langchain_huggingface）。

LangchainOpenAIEmbedder 为必交付生产实现。
LangchainHuggingfaceEmbedder 为可选实现（BGE 权重本地自备，非必交付）。
"""

from abc import ABC, abstractmethod
from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)


class BaseEmbedder(ABC):
    """Embedder 接口。"""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
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

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self._embedder.aembed_documents(texts)

    async def embed_query(self, text: str) -> list[float]:
        return await self._embedder.aembed_query(text)


class LangchainHuggingfaceEmbedder(BaseEmbedder):
    """langchain-huggingface embedding 可选实现（BGE 权重本地自备）。"""

    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5") -> None:
        from langchain_huggingface import HuggingFaceEmbeddings

        self._embedder = HuggingFaceEmbeddings(model_name=model_name)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self._embedder.aembed_documents(texts)

    async def embed_query(self, text: str) -> list[float]:
        return await self._embedder.aembed_query(text)


def build_embedder(backend: str, **kwargs: Any) -> BaseEmbedder:
    """工厂：按 EMBEDDING_BACKEND 切换。"""
    if backend == "langchain_huggingface":
        return LangchainHuggingfaceEmbedder(model_name=kwargs.get("model", "BAAI/bge-small-zh-v1.5"))
    return LangchainOpenAIEmbedder(
        api_key=kwargs.get("api_key", ""),
        model=kwargs.get("model", "text-embedding-3-small"),
        base_url=kwargs.get("base_url", ""),
    )
