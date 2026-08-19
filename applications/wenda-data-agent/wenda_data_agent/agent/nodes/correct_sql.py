"""correct_sql 节点：LLM 纠正循环，加载 prompts/correct_sql.prompt。"""

from pathlib import Path
from typing import Any

from wenda_data_agent.agent.llm import LLMClient

_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "correct_sql.prompt"


def _load_prompt() -> str:
    if _PROMPT_PATH.exists():
        return _PROMPT_PATH.read_text(encoding="utf-8")
    return "纠正以下 SQL：\n{sql}\n错误：{error}"


async def correct_sql(state: dict[str, Any]) -> dict[str, Any]:
    sql = state.get("sql", "")
    error = state.get("error", "")
    query = state.get("query", "")
    retrieved_info = state.get("retrieved_info", "")
    llm: LLMClient | None = state.get("llm")
    correct_count = state.get("correct_count", 0)

    if llm is None or not llm.enabled:
        return {"sql": sql, "error": error, "correct_count": correct_count + 1}

    if correct_count >= state.get("sql_max_correct_retries", 3):
        return {"sql": sql, "error": "纠正次数已达上限"}

    prompt_template = _load_prompt()
    prompt = prompt_template.format(
        query=query,
        table_infos=retrieved_info,
        metric_infos="",
        date_info="",
        db_info="postgresql",
        sql=sql,
        error=error,
    )
    corrected = await llm.invoke(prompt)
    return {"sql": corrected, "error": "", "correct_count": correct_count + 1}
