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
