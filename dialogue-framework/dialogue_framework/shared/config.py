"""集中配置：全部来自环境变量 / .env，pydantic-settings 校验。

对齐 app/config.py 风格；dialogue-framework 独立配置命名空间。
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 服务
    host: str = "0.0.0.0"
    port: int = 8001

    # 存储后端：json（开发零依赖）| postgres（生产）
    store_backend: str = "json"
    database_url: str = ""  # STORE_BACKEND=postgres 时必填

    # 检索后端
    retrieval_backend: str = "pgvector"
    # 图检索后端（可插拔）：pgvector | neo4j
    graph_backend: str = "pgvector"

    # LLM（OpenAI 兼容，对齐 langchain-openai>=0.3）
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_fallback_model: str = "gpt-4o-mini"
    llm_timeout: float = 60.0

    # Embedding 后端（可插拔）：langchain_openai | langchain_huggingface
    embedding_backend: str = "langchain_openai"
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_model: str = "bge-small-zh"

    # 向量维度
    vector_dim: int = 512
    # 检索 top_k
    retrieval_top_k: int = 4

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
