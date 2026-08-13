"""LangchainOpenAIEmbedder：langchain-openai 远程 embedding 生产实现。"""

from dialogue_framework.shared.config import get_settings


class LangchainOpenAIEmbedder:
    """langchain-openai 远程 embedding（生产默认）。"""

    def __init__(self) -> None:
        from langchain_openai import OpenAIEmbeddings

        settings = get_settings()
        self._embeddings = OpenAIEmbeddings(
            model=settings.embedding_model,
            api_key=settings.embedding_api_key or settings.llm_api_key,
            base_url=settings.embedding_base_url or None,
        )

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return await self._embeddings.aembed_documents(texts)

    async def embed_query(self, query: str) -> list[float]:
        return await self._embeddings.aembed_query(query)
