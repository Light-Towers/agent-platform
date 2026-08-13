"""LangchainOpenAIEmbedder：复用 agent_core.llm.embedding，从 settings 注入参数。"""

from agent_core.llm.embedding import LangchainOpenAIEmbedder as _CoreEmbedder
from dialogue_framework.shared.config import get_settings


class LangchainOpenAIEmbedder(_CoreEmbedder):
    """langchain-openai 远程 embedding（生产默认）。

    从 dialogue_framework settings 读取 api_key/model/base_url，
    委托给 agent_core.llm.embedding.LangchainOpenAIEmbedder。
    """

    def __init__(self) -> None:
        settings = get_settings()
        super().__init__(
            api_key=settings.embedding_api_key or settings.llm_api_key,
            model=settings.embedding_model,
            base_url=settings.embedding_base_url or "",
        )
