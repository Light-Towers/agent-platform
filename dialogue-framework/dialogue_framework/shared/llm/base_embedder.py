"""BaseEmbedder Protocol：embedding 可插拔接口抽象。

生产实现：LangchainOpenAIEmbedder（langchain-openai 远程，默认）。
可选实现：LangchainHuggingfaceEmbedder（BGE 本地，权重不入库，可跳过）。
"""

from typing import Protocol


class BaseEmbedder(Protocol):
    """embedding 客户端协议。"""

    async def embed_texts(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, query: str) -> list[float]: ...
