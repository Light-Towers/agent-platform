"""集中配置：pydantic-settings + YAML 覆盖，对齐 app/config.py 风格。

环境变量优先级 > YAML > 默认值。
"""

from functools import lru_cache
from pathlib import Path
from typing import List

import yaml
from pydantic import Field
from shared_schemas.settings import BaseLLMSettings


class Settings(BaseLLMSettings):
    # 服务
    host: str = "0.0.0.0"
    port: int = 8000

    # 元知识库 DSN（Postgres）
    meta_db_dsn: str = ""
    # 业务数仓 DSN（Postgres 只读）
    dw_db_dsn: str = ""

    # 表前缀
    table_prefix: str = "nl2sql_"

    # 数据源维度（P1-3/P1-4/P1-6）：问数只读消费方，源由用户在会话里显式选定。
    # 单源部署（一个 dw DSN）时这三项描述默认源；datasource_dialect 留空则按
    # dw_db_dsn 的 scheme 自动探测（mysql:// → mysql，其余 postgres）。
    datasource_id: str = "dw"
    datasource_label: str = ""  # 口径标签（P1-3②），随响应体返回，如"数仓 T+1、已清洗"
    datasource_dialect: str = ""  # 空 = 按 dw_db_dsn scheme 探测；否则 postgres|mysql

    # LLM 补充字段
    llm_max_retries: int = 3

    # Embedding 补充字段（覆盖基类默认值）
    embedding_backend: str = "langchain_openai"
    embedding_model: str = "text-embedding-3-small"
    vector_dim: int = 1536

    # 检索
    retrieval_top_k: int = 10  # 区别于 agent_server(4)/knowledge(5)：本服务为专用 Text-to-SQL，元知识召回需广泛覆盖表/列/指标
    rrf_k: int = 60
    # 向量召回相对截断（P0-5④）：绝对余弦分跨查询不可比，改为 top-k 内
    # "与最佳分的差超过 margin 即截断"。0 = 关闭（纯 top-k）。
    retrieval_score_margin: float = 0.15

    # 连接池（psycopg_pool 显式配额；取值依据见 clients/pg_pool.py）
    # meta：检索 + CRUD 共用，毫秒级画像 ⇒ min 1（按需增长，不预占）、max 对齐
    #      agent_runtime.db 的 db_pool_max_size 默认 20、语句 5s（超过即缺索引）
    meta_db_pool_min_size: int = 1
    meta_db_pool_max_size: int = 20
    meta_db_pool_timeout: float = 5.0
    meta_db_statement_timeout_ms: int = 5000
    # dw：执行 LLM 生成的 SQL，OLAP 长查询画像 ⇒ max 10（连接更贵）、语句 30s
    #      （聚合扫描可合法跑数十秒，真正的护栏是 LIMIT + 连接级只读）
    dw_db_pool_min_size: int = 1
    dw_db_pool_max_size: int = 10
    dw_db_pool_timeout: float = 10.0
    dw_db_statement_timeout_ms: int = 30000
    # 业务数仓池连接级只读（第二道防线）。默认 true；置 false 前必须确认业务库
    # 账号本身已 `GRANT SELECT ONLY`——否则只剩 DwRepository 里那道会话级 SET，
    # 而它是可被连接重置打穿的。真正第一道防线永远是账号权限，不是这个开关。
    dw_db_connection_read_only: bool = True

    # SQL 守卫（强制只读）
    sql_read_only_guard: bool = True
    sql_max_rows: int = 1000  # 区别于 agent_server(100)：本服务为专职数据查询工具，结果由前端 UI 展示而非注入 LLM prompt
    sql_max_correct_retries: int = 3
    # 进模型的结果体量上限（§5.11-V3 双上限分离）：与 sql_max_rows（返回 UI）分开——
    # 1000 行宽表几十 MB 直接进 prompt 会爆上下文。行数/字节双阈值，先到先截。
    sql_max_rows_for_prompt: int = 100
    sql_prompt_max_bytes: int = 51200  # 50KB
    # 聚合引导阈值（§5.11-V3-3）：候选表行数估值超过它时，生成 prompt 追加
    # "优先聚合"引导。估值来自漂移检测的表统计（P0-3），无估值则不引导。
    aggregation_row_threshold: int = 1_000_000

    # 分词器：jieba | bigram（jieba 需装可选 extra `[tokenizer]`，缺包时告警降级 bigram）
    tokenizer: str = "bigram"

    # 取值只读探针（P0-9/P0-7）：取值匹配的唯一源侧入口。默认全关的
    # linkable 白名单 + 短超时 + 信号量 + 版本缓存；分区列配了就必须带
    # 最新分区值（取不到就不探，不做全分区扫描）。
    value_probe_enabled: bool = True
    value_probe_limit: int = 50
    value_probe_timeout_ms: int = 2000
    value_probe_concurrency: int = 2
    value_probe_cache_ttl_seconds: int = 900
    # 源数据版本（Doris 最新分区号 / MySQL 水位）；空 = TTL 分桶兜底
    source_snapshot_sql: str = ""
    # 分区谓词（Doris 场景必配）：配了分区列但取不到最新值 ⇒ 不探
    dw_partition_column: str = ""
    dw_latest_partition_sql: str = ""
    dw_partition_required: bool = True
    # P1-2 linkable 白名单（"table.column" 全限定名；默认空 = 全关）
    linkable_columns: List[str] = Field(default_factory=list)

    # 生成期日期上下文的口径说明（P0-11①，2026-10-18）：系统日期由代码注入，
    # 数据新鲜度由部署方声明（如"数据为 T+1 快照，按数据日期理解相对时间"）。
    # 默认空 = 只注入系统日期。
    date_context_note: str = ""

    # 负载隔离（P1-5 / S-6）：应用侧并发闸 + 每租户/用户限流。全 0 = 关闭
    # （老部署逐字节一致）。Doris 侧 workload group 管不到应用层这条。
    # query_max_concurrency：同时在跑的图执行上限，超出排队，排队超过
    #   acquire_timeout 直接拒绝（快失败，连接池配额扛不住无限排队）。
    # query_rate_limit_per_min：按 tenant_id/user_id 维度的每分钟请求上限。
    query_max_concurrency: int = 0
    query_rate_limit_per_min: int = 0
    query_acquire_timeout: float = 5.0

    # metric_config 入参守卫（S-2）：客户端注入的元知识必须过两道闸——
    # allowed_tables 非空时，metric_config 声明的每个表都要在清单内（空 = 不校验，
    # 老部署向后兼容）；metric_config_max_items 限总条目数防 prompt 被撑爆。
    allowed_tables: List[str] = Field(default_factory=list)
    metric_config_max_items: int = 200

    # 数据权限（§5.9 L2/L3）：sensitive_columns 是"一份声明两处消费"的敏感列
    # 清单（"table.column" 全限定，小写）——同时驱动 L2 guard 黑名单与 L3 结果
    # 层脱敏。L1（账号 GRANT + 脱敏视图）在 DB 侧，应用不建 DDL，见 README。
    sensitive_columns: List[str] = Field(default_factory=list)
    # L3 结果层脱敏：非 admin 角色对敏感列投影掩码。掩码保留首尾各 keep 个字符，
    # 其余打 *；keep=0 = 全掩码。admin_roles 里的角色看全量。
    result_masking_enabled: bool = True
    mask_keep_chars: int = 1
    admin_roles: List[str] = Field(default_factory=lambda: ["admin"])
    # L3 角色来源（服务端断言，非客户端请求体）：未接 ADR-0007 身份门前的
    # 最小权限默认。接入身份门后改为从断言身份取。置 admin 需显式改配置。
    default_query_role: str = "analyst"

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


#: YAML `pool.<source>.<key>` → Settings 字段名。字段名不对称
#: （statement_timeout_ms 没有 pool_ 中缀），显式映射不猜名。
_POOL_KEY_TO_FIELD = {
    ("meta_db", "min_size"): "meta_db_pool_min_size",
    ("meta_db", "max_size"): "meta_db_pool_max_size",
    ("meta_db", "timeout"): "meta_db_pool_timeout",
    ("meta_db", "statement_timeout_ms"): "meta_db_statement_timeout_ms",
    ("dw_db", "min_size"): "dw_db_pool_min_size",
    ("dw_db", "max_size"): "dw_db_pool_max_size",
    ("dw_db", "timeout"): "dw_db_pool_timeout",
    ("dw_db", "statement_timeout_ms"): "dw_db_statement_timeout_ms",
}


def _pool_overrides(app_yaml: dict) -> dict:
    """从 app_config.yaml 的 `pool:` 段提取覆盖项。

    只覆盖 YAML 里**显式出现**的键，缺项回落 Field 默认，不整段替换——
    否则"YAML 只写一个键"会把其余键打回代码默认，与环境变量优先级语义相悖。
    """
    pool_yaml = app_yaml.get("pool") or {}
    out: dict = {}
    for source in ("meta_db", "dw_db"):
        section = pool_yaml.get(source.removesuffix("_db")) or {}
        for key, value in section.items():
            field = _POOL_KEY_TO_FIELD.get((source, key))
            if field is None:
                raise ValueError(f"app_config.yaml pool.{source.removesuffix('_db')} 出现未知键: {key}")
            out[field] = value
    return out


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
        overrides["retrieval_score_margin"] = app_yaml["retrieval"].get("score_margin", 0.15)
    if "sql" in app_yaml:
        overrides["sql_read_only_guard"] = app_yaml["sql"].get("read_only_guard", True)
        overrides["sql_max_rows"] = app_yaml["sql"].get("max_rows", 1000)
        overrides["sql_max_correct_retries"] = app_yaml["sql"].get("max_correct_retries", 3)
        overrides["sql_max_rows_for_prompt"] = app_yaml["sql"].get("max_rows_for_prompt", 100)
        overrides["sql_prompt_max_bytes"] = app_yaml["sql"].get("prompt_max_bytes", 51200)
        overrides["aggregation_row_threshold"] = app_yaml["sql"].get("aggregation_row_threshold", 1_000_000)
    if "tokenizer" in app_yaml:
        overrides["tokenizer"] = app_yaml["tokenizer"].get("type", "bigram")
    load_yaml = app_yaml.get("load_guard") or {}
    if load_yaml:
        overrides["query_max_concurrency"] = load_yaml.get("max_concurrency", 0)
        overrides["query_rate_limit_per_min"] = load_yaml.get("rate_limit_per_min", 0)
        overrides["query_acquire_timeout"] = load_yaml.get("acquire_timeout", 5.0)
    guard_yaml = app_yaml.get("metric_config_guard") or {}
    if guard_yaml:
        overrides["allowed_tables"] = guard_yaml.get("allowed_tables", []) or []
        overrides["metric_config_max_items"] = guard_yaml.get("max_items", 200)
    perm_yaml = app_yaml.get("data_permission") or {}
    if perm_yaml:
        overrides["sensitive_columns"] = perm_yaml.get("sensitive_columns", []) or []
        overrides["result_masking_enabled"] = perm_yaml.get("result_masking_enabled", True)
        overrides["mask_keep_chars"] = perm_yaml.get("mask_keep_chars", 1)
        overrides["admin_roles"] = perm_yaml.get("admin_roles", ["admin"]) or ["admin"]
        overrides["default_query_role"] = perm_yaml.get("default_query_role", "analyst")
    datasource_yaml = app_yaml.get("datasource") or {}
    if datasource_yaml:
        overrides["datasource_id"] = datasource_yaml.get("id", "dw")
        overrides["datasource_label"] = datasource_yaml.get("label", "") or ""
        overrides["datasource_dialect"] = datasource_yaml.get("dialect", "") or ""
    probe_yaml = app_yaml.get("value_probe") or {}
    if probe_yaml:
        overrides["value_probe_enabled"] = probe_yaml.get("enabled", True)
        overrides["value_probe_limit"] = probe_yaml.get("limit", 50)
        overrides["value_probe_timeout_ms"] = probe_yaml.get("timeout_ms", 2000)
        overrides["value_probe_concurrency"] = probe_yaml.get("concurrency", 2)
        overrides["value_probe_cache_ttl_seconds"] = probe_yaml.get("cache_ttl_seconds", 900)
        overrides["source_snapshot_sql"] = probe_yaml.get("snapshot_sql", "")
        overrides["dw_partition_column"] = probe_yaml.get("partition_column", "")
        overrides["dw_latest_partition_sql"] = probe_yaml.get("latest_partition_sql", "")
        overrides["dw_partition_required"] = probe_yaml.get("partition_required", True)
        overrides["linkable_columns"] = probe_yaml.get("linkable_columns", []) or []
    if "meta_db" in meta_yaml:
        overrides["table_prefix"] = meta_yaml["meta_db"].get("table_prefix", "nl2sql_")
    if "pool" in app_yaml:
        overrides.update(_pool_overrides(app_yaml))

    return Settings(**overrides)
