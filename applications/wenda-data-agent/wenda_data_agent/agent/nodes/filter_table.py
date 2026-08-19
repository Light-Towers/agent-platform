"""filter_table 节点：LLM 过滤表。"""

import json
from typing import Any

from wenda_data_agent.agent.llm import LLMClient


async def filter_table(state: dict[str, Any]) -> dict[str, Any]:
    query = state.get("query", "")
    tables = state.get("tables", [])
    llm: LLMClient | None = state.get("llm")

    if not tables:
        return {"tables": []}

    if llm is not None and llm.enabled:
        prompt = f"从候选表中选择回答问题所需的表，输出 JSON 数组：\n问题：{query}\n候选表：{json.dumps(tables, ensure_ascii=False)}"
        result = await llm.invoke(prompt)
        try:
            filtered = json.loads(result)
            if isinstance(filtered, list):
                return {"tables": filtered}
        except (json.JSONDecodeError, TypeError):
            pass

    return {"tables": tables}
