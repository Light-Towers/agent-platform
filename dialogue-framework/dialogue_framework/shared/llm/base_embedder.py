"""BaseEmbedder：复用 agent_core.llm.embedding.BaseEmbedder。

生产实现：LangchainOpenAIEmbedder（langchain-openai 远程，默认）。
可选实现：LangchainHuggingfaceEmbedder（BGE 本地，权重不入库，可跳过）。
"""

from agent_core.llm.embedding import BaseEmbedder

__all__ = ["BaseEmbedder"]
