"""集中配置：pydantic-settings + YAML 覆盖，对齐 app/config.py 风格。

环境变量优先级 > YAML > 默认值。
"""

from functools import lru_cache
from pathlib import Path

import yaml
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

    # 生成期日期上下文的口径说明（P0-11①，2026-10-18）：系统日期由代码注入，
    # 数据新鲜度由部署方声明（如"数据为 T+1 快照，按数据日期理解相对时间"）。
    # 默认空 = 只注入系统日期。
    date_context_note: str = ""

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
    if "meta_db" in meta_yaml:
        overrides["table_prefix"] = meta_yaml["meta_db"].get("table_prefix", "nl2sql_")
    if "pool" in app_yaml:
        overrides.update(_pool_overrides(app_yaml))

    return Settings(**overrides)
