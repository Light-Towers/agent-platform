"""集中配置：全部来自环境变量 / .env，pydantic-settings 校验。"""

from functools import lru_cache

from pydantic_settings import SettingsConfigDict
from shared_schemas.settings import BaseLLMSettings


class Settings(BaseLLMSettings):
    # model_ 前缀字段（如 model_context_window）与 pydantic 保留命名空间冲突，
    # 显式清空 protected_namespaces 以消除警告
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", protected_namespaces=()
    )

    # 服务
    host: str = "0.0.0.0"
    port: int = 8000
    api_key: str = ""  # 非空时启用 X-API-Key 认证，并忽略客户端 thread_id

    # 存储
    database_url: str = ""  # 空 = 内存模式（无持久化，仅开发）
    db_pool_max_size: int = 20  # 连接池上限（高并发 admission 全局限流 100/s 时避免池耗尽）

    # LLM 补充字段
    llm_fallback_model: str = "gpt-4o-mini"

    # Embedding 补充字段
    embedding_mode: str = "auto"  # auto | mock | remote

    # 联网搜索
    search_api_key: str = ""

    # Text-to-SQL
    sql_dsn: str = ""
    sql_max_rows: int = 100

    # 健壮性
    cache_enabled: bool = True
    cache_threshold: float = 0.05  # 余弦距离阈值，小于该值视为同义命中
    memory_enabled: bool = True
    memory_extraction_enabled: bool = False  # 优化 H：LLM 抽取结构化事实（默认关，无 LLM 时退化存原文）
    memory_forget_threshold: float = 0.1  # 优化 H：低价值记忆惰性淘汰阈值（importance）
    breaker_failure_threshold: int = 3
    breaker_recovery_seconds: float = 30.0

    # 可观测
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = ""

    # RAG
    rag_top_k: int = 4
    # Rerank：RRF 融合后是否用硅基流动 bge-reranker-v2-m3 重排 top-K
    rerank_enabled: bool = False
    rerank_top_n: int = 8  # 融合后送入 rerank 的候选数（>= rag_top_k）
    rerank_api_key: str = ""
    rerank_base_url: str = "https://api.siliconflow.cn/v1"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"

    # 图控制
    max_iterations: int = 2

    # 上下文压缩
    compaction_enabled: bool = True
    compaction_threshold_ratio: float = 0.8  # 占模型窗口比例，超过则触发压缩
    # 模型上下文窗口 token 数。务必按实际模型填写（可用环境变量 MODEL_CONTEXT_WINDOW 覆盖），
    # 切勿依赖 128000 默认值当成万能值：qwen-max 仅 32768、qwen-long 达 1000000，
    # 填错会导致压缩触发比例与真实窗口脱节。
    model_context_window: int = 128000  # 默认 128K（OpenAI 系常见值），按模型改

    # Phase 2: 会话并发协调
    coordination_enabled: bool = True
    coordination_policy: str = "queue"  # queue | reject

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

    # 输入护栏（opt-in，默认 false）：PII 脱敏 + prompt injection 检测
    guard_enabled: bool = False

    # Plan-F Phase 2: Planner 实现选择（deterministic | graph | agentic | auto），PLANNER env 覆盖。
    # ``auto`` 启用 Phase A Mode Selector：按问题/能力自动选 deterministic/workflow/graph/agentic；
    # 其余值为强制 override（调试/灰度）。
    planner: str = "deterministic"

    # Plan-F Phase 3: Skill 组合治理（agentic 组合路径的护栏边界；
    # deterministic 静态 DAG 天然无环，不使用这些限制）
    max_skill_depth: int = 4
    max_steps: int = 20

    # Plan-F Phase 3: 单次 execution 的 wall-clock 上限（秒），None/0 不启用；
    # 经 PlannerRuntime.max_duration_seconds 注入 execution() 边界，由 execute_graph
    # 按层检查 deadline 提前终止（超限产出 error 事件）。
    max_execution_seconds: float = 60.0

    # Plan-F Context Pipeline：统一上下文组装（agent_runtime/context/）
    context_budget_tool_results_ratio: float = 0.35  # tool_results 层占比
    tool_result_max_tokens: int = 8192  # 单条工具结果超此阈值则外置 + 截断视图
    tool_result_store_dir: str = ""  # 空则复用 session_dir
    memory_gate_top_k: int = 5  # 记忆召回门控：预算内最多注入的条数
    tool_result_compression_enabled: bool = False  # opt-in：Skill 出口统一压缩（默认关，避免改变现有返回结构）

    # CORS：允许的前端来源（逗号分隔），为空时默认回环 127.0.0.1:5173
    cors_allow_origins: str = ""

    # §20: 运行时模式（决定持久化后端与 fail-fast 行为）
    # local       -> InMemory 后端，无需 DATABASE_URL（开发/测试默认）
    # single_node -> PG 可选（有 DATABASE_URL 用 PG，无则降级 InMemory）
    # distributed -> PG 必须（无 DATABASE_URL 启动即报错，fail fast）
    runtime_mode: str = "local"

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
