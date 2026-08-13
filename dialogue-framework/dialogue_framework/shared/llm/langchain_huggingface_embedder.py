"""LangchainHuggingfaceEmbedder：BGE 本地 embedding 可选实现。

[可选/可跳过] BGE 权重本地自备，非必交付。
对齐 spec「BGE 不生产化入栈」精神：缺省 EMBEDDING_BACKEND=langchain_openai 时本文件不被加载。
需 EMBEDDING_BACKEND=langchain_huggingface 且本地放置 BGE 权重（约 390MB）。
"""

from dialogue_framework.shared.config import get_settings
from dialogue_framework.shared.llm.langchain_openai_embedder import LangchainOpenAIEmbedder


class LangchainHuggingfaceEmbedder:
    """BGE 本地 embedding（可选，权重本地自备不入库）。"""

    def __init__(self, model_path: str) -> None:
        from langchain_huggingface import HuggingFaceEmbeddings

        self._embeddings = HuggingFaceEmbeddings(model_name=model_path)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self._embeddings.embed_documents(texts)

    async def embed_query(self, query: str) -> list[float]:
        return self._embeddings.embed_query(query)


def build_embedder():
    """按 EMBEDDING_BACKEND 环境变量切换 embedding 实现。"""
    settings = get_settings()
    if settings.embedding_backend == "langchain_huggingface":
        from dialogue_framework.shared.constants import DEFAULT_MODELS_PATH

        return LangchainHuggingfaceEmbedder(model_path=DEFAULT_MODELS_PATH)
    return LangchainOpenAIEmbedder()
