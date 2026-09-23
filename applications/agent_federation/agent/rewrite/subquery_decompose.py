"""子问题分解：一问拆多问并行。

用 LLM 产出 [{subquery, intent}] 列表，并行调 Phase 2 路由。
"""

from __future__ import annotations

import json
from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)


async def decompose(query: str, model: Any = None) -> list[dict[str, str]]:
    """子问题分解。

    Args:
        query: 用户查询
        model: LLM 模型

    Returns:
        [{"subquery": "...", "intent": "..."}, ...] 或 []（不需拆分）
    """
    if model is None:
        from agent.llm import model as _default_model
        model = _default_model

    try:
        from langchain_core.messages import HumanMessage

        from agent.prompts import rewrite_content

        prompt = f"""{rewrite_content['decompose']['system_prompt']}

用户查询：{query}

结果："""

        resp = await model.ainvoke([HumanMessage(content=prompt)])
        content = resp.content if hasattr(resp, "content") else str(resp)

        import re
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            result = json.loads(match.group())
            if isinstance(result, list) and result:
                logger.info("子问题分解: %r → %d 子问题", query, len(result))
                return result
    except Exception as e:
        logger.warning("子问题分解失败: %s", e)

    return []
