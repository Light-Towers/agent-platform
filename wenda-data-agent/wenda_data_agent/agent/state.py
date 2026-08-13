"""DataAgentState：Text-to-SQL 管线状态。"""

from typing import Any, TypedDict


class DataAgentState(TypedDict, total=False):
    query: str
    keywords: list[str]
    tables: list[dict[str, Any]]
    columns: list[dict[str, Any]]
    metrics: list[dict[str, Any]]
    values: list[dict[str, Any]]
    retrieved_info: str
    extra_context: str
    sql: str
    sql_valid: bool
    error: str
    result: Any
    answer: str
    correct_count: int
