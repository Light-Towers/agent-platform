"""共享配置基类：LLM / Embedding 连接参数。

三个 BaseSettings 包（app / dialogue-framework / wenda-data-agent）
共同继承 BaseLLMSettings，消除 8 个公共字段的重复声明。
各包可在子类中覆盖默认值或追加包专属字段。
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseLLMSettings(BaseSettings):
    """LLM + Embedding 连接参数基类（8 个公共字段）。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LLM（OpenAI 兼容）
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_timeout: float = 60.0

    # Embedding
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_model: str = "bge-small-zh"
    vector_dim: int = 512

    # Rerank（硅基流动 API 模式；空 key 时关闭，回退到无 rerank 的融合排序）
    rerank_api_key: str = ""
    rerank_base_url: str = "https://api.siliconflow.cn/v1"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_enabled: bool = False

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key)

    @property
    def rerank_effective_enabled(self) -> bool:
        """配置了 key 且显式开启时才走远程 rerank。"""
        return self.rerank_enabled and bool(self.rerank_api_key)


__all__ = ["BaseLLMSettings"]
