"""L2 LLM 细判：仅当 L1 置信度 < 阈值时触发。

在 L1 top-3 候选里用 LLM 细判，复用 kefu 决策规则表模式。
"""

from __future__ import annotations

import json
from typing import Any

from agent_core.logging import get_logger

from agent.intent.classifier import classify as _l1_classify

logger = get_logger(__name__)

_L2_THRESHOLD = 0.8
_CLARIFY_THRESHOLD = 0.5


async def llm_judge(query: str, candidates: list[dict], model: Any = None) -> dict[str, Any]:
    """L2 LLM 细判。

    Args:
        query: 用户查询
        candidates: L1 top-K 候选 [{"intent": "...", "confidence": ...}, ...]
        model: LLM 模型（None 时用默认 model）

    Returns:
        {"intent": "...", "confidence": ..., "source": "l2"}
    """
    if model is None:
        from agent.llm import model as _default_model
        model = _default_model

    candidate_desc = "\n".join(
        f"  {i+1}. {c['intent']} (L1 置信度: {c['confidence']:.2f})"
        for i, c in enumerate(candidates)
    )

    prompt = f"""请判断用户查询最匹配哪个意图。

用户查询：{query}

候选意图：
{candidate_desc}

只返回一行 JSON，格式：{{"intent": "意图标签", "confidence": 0.0-1.0}}

意图说明：
- text_to_sql: 数据库查询/统计/计算
- rag_knowledge: 知识库/制度/流程
- customer_service: 客服/退换/物流
- web_search: 搜索/新闻/趋势
- chitchat: 闲聊/问候"""

    try:
        from langchain_core.messages import HumanMessage
        resp = await model.ainvoke([HumanMessage(content=prompt)])
        content = resp.content if hasattr(resp, "content") else str(resp)

        import re
        match = re.search(r'\{[^}]*"intent"[^}]*\}', content)
        if match:
            result = json.loads(match.group())
            return {
                "intent": result.get("intent", candidates[0]["intent"]),
                "confidence": float(result.get("confidence", 0.7)),
                "source": "l2",
            }
    except Exception as e:
        logger.warning("L2 LLM 细判失败: %s，回退 L1", e)

    return {"intent": candidates[0]["intent"], "confidence": candidates[0]["confidence"], "source": "l1_fallback"}


async def classify_with_fallback(query: str, model: Any = None) -> dict[str, Any]:
    """L1 + L2 合并分类。

    L1 置信度 >= 0.8 → 直出
    L1 置信度 < 0.8 → L2 LLM 细判
    最终置信度 < 0.5 → clarify 反问
    """
    l1_result = _l1_classify(query)
    primary = l1_result["primary"]

    if primary["confidence"] >= _L2_THRESHOLD:
        return {
            "primary": primary,
            "candidates": l1_result["candidates"],
            "source": "l1",
            "need_clarify": False,
        }

    l2_result = await llm_judge(query, l1_result["candidates"], model)

    need_clarify = l2_result["confidence"] < _CLARIFY_THRESHOLD

    return {
        "primary": l2_result,
        "candidates": l1_result["candidates"],
        "source": l2_result["source"],
        "need_clarify": need_clarify,
    }
