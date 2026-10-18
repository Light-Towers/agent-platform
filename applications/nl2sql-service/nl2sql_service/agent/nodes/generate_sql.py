"""generate_sql 节点：LLM 生成 SQL，加载 prompts/generate_sql.prompt。

2026-10-18 审计（方案 P0-11）：四个槽必须来自 state，而不是恒空串——
`metric_infos` 此前固定 `""`（指标口径白召回）、`date_info` 固定 `""`（相对时间无锚点）、
`table_infos` 只有 RRF 混合 JSON（没有表级视图）。
"""

from typing import Any

from nl2sql_service.agent.llm import LLMClient
from nl2sql_service.agent.nodes._prompt import json_block, load_prompt, render

_FALLBACK = "根据以下信息生成 SQL：\n{query}\n表信息：{table_infos}\n指标信息：{metric_infos}"


def build_table_infos(state: dict[str, Any]) -> str:
    """生成期表上下文：表 / 列 / 取值分块。

    优先用 state 里各自的结构化列表；三者全空时回落到 merge 节点产出的
    融合文本（无元知识的降级路径）。
    """
    tables = state.get("tables", [])
    columns = state.get("columns", [])
    values = state.get("values", [])
    if not (tables or columns or values):
        return state.get("retrieved_info", "")
    return (
        f"【表】{json_block(tables)}\n"
        f"【列】{json_block(columns)}\n"
        f"【取值】{json_block(values)}"
    )


async def generate_sql(state: dict[str, Any]) -> dict[str, Any]:
    query = state.get("query", "")
    llm: LLMClient | None = state.get("llm")

    if llm is None or not llm.enabled:
        return {"sql": "", "error": "LLM not configured"}

    prompt = render(
        load_prompt("generate_sql.prompt", _FALLBACK),
        query=query,
        table_infos=build_table_infos(state),
        metric_infos=json_block(state.get("metrics", [])),
        date_info=state.get("date_info", ""),
        db_info=state.get("extra_context") or "PostgreSQL（方言 postgres；只输出单条只读 SELECT）",
    )
    sql = await llm.invoke(prompt)
    return {"sql": sql, "error": ""}
