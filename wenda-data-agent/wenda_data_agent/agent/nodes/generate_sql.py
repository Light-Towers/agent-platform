"""generate_sql 节点：LLM 生成 SQL，加载 prompts/generate_sql.prompt。"""

from pathlib import Path
from typing import Any

from wenda_data_agent.agent.llm import LLMClient

_PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "generate_sql.prompt"


def _load_prompt() -> str:
    if _PROMPT_PATH.exists():
        return _PROMPT_PATH.read_text(encoding="utf-8")
    return "根据以下信息生成 SQL：\n{query}\n表信息：{table_infos}\n指标信息：{metric_infos}"


async def generate_sql(state: dict[str, Any]) -> dict[str, Any]:
    query = state.get("query", "")
    retrieved_info = state.get("retrieved_info", "")
    extra_context = state.get("extra_context", "")
    llm: LLMClient | None = state.get("llm")

    if llm is None or not llm.enabled:
        return {"sql": "", "error": "LLM not configured"}

    prompt_template = _load_prompt()
    prompt = prompt_template.format(
        query=query,
        table_infos=retrieved_info,
        metric_infos="",
        date_info="",
        db_info=extra_context or "postgresql",
    )
    sql = await llm.invoke(prompt)
    return {"sql": sql, "error": ""}
