"""Embedding 客户端管理：复用 agent_core.llm.embedding。"""

from agent_core.llm.embedding import (
    BaseEmbedder,
    LangchainHuggingfaceEmbedder,
    LangchainOpenAIEmbedder,
    build_embedder,
)

__all__ = [
    "BaseEmbedder",
    "LangchainHuggingfaceEmbedder",
    "LangchainOpenAIEmbedder",
    "build_embedder",
]
