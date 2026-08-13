"""集中配置：全部来自环境变量 / .env，pydantic-settings 校验。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 服务
    host: str = "0.0.0.0"
    port: int = 8000
    api_key: str = ""  # 非空时启用 X-API-Key 认证，并忽略客户端 thread_id

    # 存储
    database_url: str = ""  # 空 = 内存模式（无持久化，仅开发）
    vector_dim: int = 512

    # LLM（OpenAI 兼容）
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_fallback_model: str = "gpt-4o-mini"
    llm_timeout: float = 60.0

    # Embedding
    embedding_mode: str = "auto"  # auto | mock | remote
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = "bge-small-zh"

    # 联网搜索
    search_api_key: str = ""

    # Text-to-SQL
    sql_dsn: str = ""
    sql_max_rows: int = 100

    # 健壮性
    cache_enabled: bool = True
    cache_threshold: float = 0.05  # 余弦距离阈值，小于该值视为同义命中
    memory_enabled: bool = True
    breaker_failure_threshold: int = 3
    breaker_recovery_seconds: float = 30.0

    # 可观测
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = ""

    # RAG
    rag_top_k: int = 4

    # 图控制
    max_iterations: int = 2

    # 上下文压缩
    compaction_enabled: bool = True
    compaction_threshold_ratio: float = 0.8  # 占模型窗口比例，超过则触发压缩
    model_context_window: int = 128000  # 模型上下文窗口 token 数

    # Phase 2: 会话并发协调
    coordination_enabled: bool = True
    coordination_policy: str = "queue"  # coalesce | queue | reject

    # Phase 2: durable admission（opt-in，默认 false）
    admission_enabled: bool = False
    admission_queue_capacity: int = 100
    admission_queue_timeout_seconds: float = 10.0
    admission_rate_limit_per_user: int = 10
    admission_rate_limit_per_session: int = 10
    admission_rate_limit_global: int = 100

    # Phase 2: 会话回退 revert
    revert_enabled: bool = True

    # Phase 2: OTel 接线（opt-in，默认 false）
    otel_enabled: bool = False
    otel_exporter: str = "otlp"  # otlp | jaeger | console | none
    otel_endpoint: str = ""
    otel_sampling_rate: float = 1.0
    otel_service_name: str = "agent-platform"

    # Phase 2: MCP client（opt-in，默认 false）
    mcp_enabled: bool = False
    mcp_servers: str = ""  # JSON 编码的 server 配置列表

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key)

    @property
    def db_enabled(self) -> bool:
        return bool(self.database_url)

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key and self.langfuse_host)

    @property
    def admission_effective_enabled(self) -> bool:
        return self.admission_enabled and self.db_enabled

    @property
    def otel_effective_enabled(self) -> bool:
        return self.otel_enabled and self.otel_exporter != "none"


@lru_cache
def get_settings() -> Settings:
    return Settings()
