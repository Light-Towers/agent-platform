"""Paraphraser：改写器，数据增强。

有 LLM 时用 LLM 改写，无 LLM 时用规则改写（同义词替换/句式变换）。
"""

from agent_core.logging import get_logger

logger = get_logger(__name__)

_SYNONYMS: dict[str, list[str]] = {
    "查询": ["查一下", "帮我查", "看看"],
    "统计": ["汇总", "算一下", "统计一下"],
    "介绍": ["解释", "说明", "讲讲"],
    "怎么": ["如何", "怎样"],
    "什么": ["哪些", "啥"],
}


class Paraphraser:
    """改写器：LLM 或规则改写。"""

    def __init__(self, llm=None) -> None:
        self._llm = llm

    async def rephrase(self, text: str) -> str:
        if not text:
            return text
        if self._llm is not None:
            return await self._rephrase_llm(text)
        return self._rephrase_rule(text)

    async def _rephrase_llm(self, text: str) -> str:
        try:
            from langchain_core.messages import HumanMessage

            prompt = f"改写以下句子，保持语义不变，表达方式不同：\n{text}"
            result = await self._llm.ainvoke([HumanMessage(content=prompt)])
            return result.content.strip()
        except Exception:
            logger.exception("LLM rephrase failed, fallback to rule")
            return self._rephrase_rule(text)

    def _rephrase_rule(self, text: str) -> str:
        result = text
        for word, synonyms in _SYNONYMS.items():
            if word in result:
                result = result.replace(word, synonyms[0], 1)
                break
        return result
