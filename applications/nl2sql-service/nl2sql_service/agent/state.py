"""DataAgentState：Text-to-SQL 管线状态。"""

from typing import Any, TypedDict


class DataAgentState(TypedDict, total=False):
    query: str
    keywords: list[str]
    # 单次计算的查询向量（extract_keywords 写入，三路召回共享；P0-11⑤）
    query_embedding: list[float]
    tables: list[dict[str, Any]]
    columns: list[dict[str, Any]]
    metrics: list[dict[str, Any]]
    values: list[dict[str, Any]]
    # 表间关系声明（§5.14-R3 召回；生成期 JOIN 条件显式注入）
    relations: list[dict[str, Any]]
    # 数据源维度（P1-6：召回过滤与 schema 作用域；缺省空串）
    datasource_id: str
    # 数据源口径标签（P1-3②）：随响应体返回，让答案能看出数字来自哪个源
    datasource_label: str
    retrieved_info: str
    extra_context: str
    # 生成期日期上下文（QueryService 注入；P0-11①）
    date_info: str
    sql: str
    sql_valid: bool
    # error 是对外分类消息；error_detail 是原始异常文本，只进日志/纠错回路（S-3）
    error: str
    error_detail: str
    # 执行期异常三分类（§5.11-E2）：correctable/rewritable 进 correct，fatal 不喂模型
    error_class: str
    # 已尝试的 SQL + 错误序列（correct prompt 必须带它，否则同一处错改三遍）
    attempted_sql: list[dict[str, Any]]
    # 取值核验与零结果分诊（P0-8②③）
    value_matched: list[str]
    value_unmatched: list[str]
    dict_hit: bool
    has_dimension_filter: bool
    empty_result: bool
    empty_result_reason: str
    # 方言（P1-4：按数据源分支；缺省 postgres）
    dialect: str
    result: Any
    answer: str
    correct_count: int
    context: Any
    llm: Any
    metric_config: dict[str, Any]
    # 配置面（QueryService 集中注入；§5.11-V2）
    sql_max_rows: int
    sql_max_correct_retries: int
    retrieval_top_k: int
    rrf_k: int
    tokenizer: str
    # 向量召回相对截断 margin（P0-5④；0 = 关闭）
    retrieval_score_margin: float
    # 进模型的结果体量上限（§5.11-V3 双上限分离）
    sql_max_rows_for_prompt: int
    sql_prompt_max_bytes: int
    # 漂移检测产出的表行数估值（P0-3 → 聚合引导；无估值则不引导）
    table_stats: list[dict[str, Any]]
