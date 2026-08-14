"""Embedding 工厂：复用 agent_core.llm.embedding，按 EMBEDDING_BACKEND 切换。

[可选/可跳过] BGE 权重本地自备，非必交付。
对齐 spec「BGE 不生产化入栈」精神：缺省 EMBEDDING_BACKEND=langchain_openai 时本文件不加载 BGE。
需 EMBEDDING_BACKEND=langchain_huggingface 且本地放置 BGE 权重（约 390MB）。
"""

from agent_core.llm.embedding import LangchainHuggingfaceEmbedder as _CoreHFEmbedder

from dialogue_framework.shared.config import get_settings
from dialogue_framework.shared.llm.langchain_openai_embedder import LangchainOpenAIEmbedder


class LangchainHuggingfaceEmbedder(_CoreHFEmbedder):
    """BGE 本地 embedding（可选，权重本地自备不入库）。"""

    def __init__(self, model_path: str) -> None:
        super().__init__(model_name=model_path)


def build_embedder():
    """按 EMBEDDING_BACKEND 环境变量切换 embedding 实现。"""
    settings = get_settings()
    if settings.embedding_backend == "langchain_huggingface":
        from dialogue_framework.shared.constants import DEFAULT_MODELS_PATH

        return LangchainHuggingfaceEmbedder(model_path=DEFAULT_MODELS_PATH)
    return LangchainOpenAIEmbedder()
