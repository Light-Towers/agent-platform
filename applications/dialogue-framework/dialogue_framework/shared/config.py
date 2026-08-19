"""集中配置：全部来自环境变量 / .env，pydantic-settings 校验。

对齐 app/config.py 风格；dialogue-framework 独立配置命名空间。
"""

from functools import lru_cache

from shared_schemas.settings import BaseLLMSettings


class Settings(BaseLLMSettings):
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

    # LLM 补充字段
    llm_fallback_model: str = "gpt-4o-mini"

    # Embedding 补充字段
    embedding_backend: str = "langchain_openai"

    # 检索
    retrieval_top_k: int = 4


@lru_cache
def get_settings() -> Settings:
    return Settings()
