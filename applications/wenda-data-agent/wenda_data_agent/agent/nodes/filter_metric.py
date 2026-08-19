"""filter_metric 节点：LLM 过滤指标。"""

import json
from typing import Any

from wenda_data_agent.agent.llm import LLMClient


async def filter_metric(state: dict[str, Any]) -> dict[str, Any]:
    query = state.get("query", "")
    metrics = state.get("metrics", [])
    llm: LLMClient | None = state.get("llm")

    if not metrics:
        return {"metrics": []}

    if llm is not None and llm.enabled:
        metric_names = [m.get("metric_name", "") if isinstance(m, dict) else str(m) for m in metrics]
        prompt = f"从候选指标中选择回答问题所需的指标，输出 JSON 数组：\n问题：{query}\n候选指标：{json.dumps(metric_names, ensure_ascii=False)}"
        result = await llm.invoke(prompt)
        try:
            filtered_names = json.loads(result)
            if isinstance(filtered_names, list):
                filtered = [m for m in metrics if (m.get("metric_name", "") if isinstance(m, dict) else str(m)) in filtered_names]
                return {"metrics": filtered}
        except (json.JSONDecodeError, TypeError):
            pass

    return {"metrics": metrics}
