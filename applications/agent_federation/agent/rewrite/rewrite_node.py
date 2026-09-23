"""Query 改写：指代消解 + standalone question。

复用 zhiku rewritten_query_and_itemnames.prompt 模式。
改写前后 A/B 评测（召回率/正确率）。
"""

from __future__ import annotations

from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)


async def rewrite_query(query: str, context: str = "", model: Any = None) -> str:
    """指代消解 + standalone question 改写。

    Args:
        query: 用户原始查询
        context: 对话上下文（前几轮，用于指代消解）
        model: LLM 模型（None 时用默认）

    Returns:
        改写后的 query（可独立理解）
    """
    if not context:
        return query

    if model is None:
        from agent.llm import model as _default_model
        model = _default_model

    try:
        from langchain_core.messages import HumanMessage

        from agent.prompts import rewrite_content

        prompt = f"""{rewrite_content['rewrite']['system_prompt']}

对话上下文：
{context}

用户查询：{query}

改写后的查询："""

        resp = await model.ainvoke([HumanMessage(content=prompt)])
        rewritten = resp.content if hasattr(resp, "content") else str(resp)
        rewritten = rewritten.strip()

        if rewritten and rewritten != query:
            logger.info("Query 改写: %r → %r", query, rewritten)
            return rewritten
    except Exception as e:
        logger.warning("Query 改写失败: %s，返回原始查询", e)

    return query
