"""correct_sql 节点：LLM 纠正循环，加载 prompts/correct_sql.prompt。

2026-10-18 审计（方案 P0-11④）：纠正轮上下文不得少于生成轮——此前
`table_infos` 只有融合文本、`metric_infos`/`date_info` 恒空串、表清单缺失。
"""

from typing import Any

from nl2sql_service.agent.llm import LLMClient
from nl2sql_service.agent.nodes._prompt import json_block, load_prompt, render
from nl2sql_service.agent.nodes.generate_sql import build_table_infos

_FALLBACK = "纠正以下 SQL：\n{sql}\n错误：{error}"


async def correct_sql(state: dict[str, Any]) -> dict[str, Any]:
    sql = state.get("sql", "")
    error = state.get("error", "")
    query = state.get("query", "")
    llm: LLMClient | None = state.get("llm")
    correct_count = state.get("correct_count", 0)

    if llm is None or not llm.enabled:
        return {"sql": sql, "error": error, "correct_count": correct_count + 1}

    if correct_count >= state.get("sql_max_correct_retries", 3):
        return {"sql": sql, "error": "纠正次数已达上限"}

    prompt = render(
        load_prompt("correct_sql.prompt", _FALLBACK),
        query=query,
        table_infos=build_table_infos(state),
        metric_infos=json_block(state.get("metrics", [])),
        date_info=state.get("date_info", ""),
        db_info=state.get("extra_context") or "PostgreSQL（方言 postgres；只输出单条只读 SELECT）",
        sql=sql,
        error=error,
    )
    corrected = await llm.invoke(prompt)
    return {"sql": corrected, "error": "", "correct_count": correct_count + 1}
