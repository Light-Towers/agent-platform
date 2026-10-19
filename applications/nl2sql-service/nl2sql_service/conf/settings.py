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

    # 连接池（psycopg_pool 显式配额；取值依据见 clients/pg_pool.py）
    # meta：检索 + CRUD 共用 ⇒ min 1（按需增长，不预占）、max 对齐 agent_runtime.db
    #      的 db_pool_max_size 默认 20。语句超时 15s（#106，原 5s）：DDL 承诺"ANN
    #      索引创建失败退化为顺序扫描仍可工作"，5s 把该降级路直接砍死；但仍须显著
    #      低于 dw 的 30s——meta 是交互级毫秒画像、dw 是 OLAP，分层由
    #       test_pool_factory 的 dw > meta 断言钉死，勿齐平。
    meta_db_pool_min_size: int = 1
    meta_db_pool_max_size: int = 20
    meta_db_pool_timeout: float = 5.0
    meta_db_statement_timeout_ms: int = 15000
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

    # filter_table 节点的 LLM 表过滤开关（#109，默认关）：_derive_tables 救活该节点后
    # 每请求会多一次 LLM 往返，且 LLM 输出只允许在派生清单内收窄（白名单交集）。
    # 关 = 不过滤、不产生该调用（派生表级视图照常进生成期）；开 = 多一次调用换更准的表清单。
    filter_table_enabled: bool = False

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


def _yaml_overrides(app_yaml: dict, meta_yaml: dict) -> dict:
    """收集 YAML 配置层**显式声明**的键（段在键缺 ⇒ 不插手，交 env / Field 默认）。

    不带行内默认值：旧写法 `.get(key, default)` 会让"段存在但键缺失"也产出值，
    把 Field 默认与 env 一并压掉——与"YAML 只是中间层"的定位相悖（#105）。
    """
    out: dict = {}
    if "server" in app_yaml:
        out["host"] = app_yaml["server"].get("host")
        out["port"] = app_yaml["server"].get("port")
    if "llm" in app_yaml:
        out["llm_model"] = app_yaml["llm"].get("model")
        out["llm_timeout"] = app_yaml["llm"].get("timeout")
        out["llm_max_retries"] = app_yaml["llm"].get("max_retries")
    if "embedding" in app_yaml:
        out["embedding_backend"] = app_yaml["embedding"].get("backend")
        out["embedding_model"] = app_yaml["embedding"].get("model")
        out["vector_dim"] = app_yaml["embedding"].get("vector_dim")
    if "retrieval" in app_yaml:
        out["retrieval_top_k"] = app_yaml["retrieval"].get("top_k")
        out["rrf_k"] = app_yaml["retrieval"].get("rrf_k")
    if "sql" in app_yaml:
        out["sql_read_only_guard"] = app_yaml["sql"].get("read_only_guard")
        out["sql_max_rows"] = app_yaml["sql"].get("max_rows")
        out["sql_max_correct_retries"] = app_yaml["sql"].get("max_correct_retries")
    if "tokenizer" in app_yaml:
        out["tokenizer"] = app_yaml["tokenizer"].get("type")
    if "meta_db" in meta_yaml:
        out["table_prefix"] = meta_yaml["meta_db"].get("table_prefix")
    if "pool" in app_yaml:
        out.update(_pool_overrides(app_yaml))
    return {k: v for k, v in out.items() if v is not None}


@lru_cache
def get_settings() -> Settings:
    """构造 Settings：env/.env > YAML > Field 默认（docstring 三级优先级，#105 兑现）。

    pydantic-settings 的 init kwargs 优先级**高于** env 与 .env 文件——把 YAML 值
    直接塞进构造参数，会让运维在环境变量里的覆盖**静默失效**（配了不生效、无任何
    提示；实测 `META_DB_POOL_MAX_SIZE=7` 被 app_config.yaml 的 20 压掉）。故先以
    空构造探针取 `model_fields_set`（精确区分"env/.env 显式设置"与"代码默认"），
    YAML 只补 env/.env 未覆盖的字段。一处机制覆盖全部配置段（pool 之外的
    server/llm/embedding/retrieval/sql/tokenizer 同此压制，一并修复）。
    """
    conf_dir = Path(__file__).parent
    yaml_overrides = _yaml_overrides(
        _load_yaml(conf_dir / "app_config.yaml"),
        _load_yaml(conf_dir / "meta_config.yaml"),
    )
    if not yaml_overrides:
        return Settings()
    env_set = Settings().model_fields_set
    return Settings(**{k: v for k, v in yaml_overrides.items() if k not in env_set})
