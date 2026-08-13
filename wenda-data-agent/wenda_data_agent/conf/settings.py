"""集中配置：pydantic-settings + YAML 覆盖，对齐 app/config.py 风格。

环境变量优先级 > YAML > 默认值。
"""

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 服务
    host: str = "0.0.0.0"
    port: int = 8000

    # 元知识库 DSN（Postgres）
    meta_db_dsn: str = ""
    # 业务数仓 DSN（Postgres 只读）
    dw_db_dsn: str = ""

    # 表前缀
    table_prefix: str = "wenda_data_agent_"

    # LLM
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_timeout: float = 60.0
    llm_max_retries: int = 3

    # Embedding 后端（可插拔）：langchain_openai | langchain_huggingface
    embedding_backend: str = "langchain_openai"
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_model: str = "text-embedding-3-small"
    vector_dim: int = 1536

    # 检索
    retrieval_top_k: int = 10
    rrf_k: int = 60

    # SQL 守卫（强制只读）
    sql_read_only_guard: bool = True
    sql_max_rows: int = 1000
    sql_max_correct_retries: int = 3

    # 分词器：jieba | bigram
    tokenizer: str = "bigram"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key)

    @property
    def meta_db_enabled(self) -> bool:
        return bool(self.meta_db_dsn)

    @property
    def dw_db_enabled(self) -> bool:
        return bool(self.dw_db_dsn)


def _load_yaml(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    with p.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache
def get_settings() -> Settings:
    conf_dir = Path(__file__).parent
    app_yaml = _load_yaml(conf_dir / "app_config.yaml")
    meta_yaml = _load_yaml(conf_dir / "meta_config.yaml")

    overrides: dict = {}
    if "server" in app_yaml:
        overrides["host"] = app_yaml["server"].get("host", "0.0.0.0")
        overrides["port"] = app_yaml["server"].get("port", 8000)
    if "llm" in app_yaml:
        overrides["llm_model"] = app_yaml["llm"].get("model", "gpt-4o-mini")
        overrides["llm_timeout"] = app_yaml["llm"].get("timeout", 60.0)
        overrides["llm_max_retries"] = app_yaml["llm"].get("max_retries", 3)
    if "embedding" in app_yaml:
        overrides["embedding_backend"] = app_yaml["embedding"].get("backend", "langchain_openai")
        overrides["embedding_model"] = app_yaml["embedding"].get("model", "text-embedding-3-small")
        overrides["vector_dim"] = app_yaml["embedding"].get("vector_dim", 1536)
    if "retrieval" in app_yaml:
        overrides["retrieval_top_k"] = app_yaml["retrieval"].get("top_k", 10)
        overrides["rrf_k"] = app_yaml["retrieval"].get("rrf_k", 60)
    if "sql" in app_yaml:
        overrides["sql_read_only_guard"] = app_yaml["sql"].get("read_only_guard", True)
        overrides["sql_max_rows"] = app_yaml["sql"].get("max_rows", 1000)
        overrides["sql_max_correct_retries"] = app_yaml["sql"].get("max_correct_retries", 3)
    if "tokenizer" in app_yaml:
        overrides["tokenizer"] = app_yaml["tokenizer"].get("type", "bigram")
    if "meta_db" in meta_yaml:
        overrides["table_prefix"] = meta_yaml["meta_db"].get("table_prefix", "wenda_data_agent_")

    return Settings(**overrides)
