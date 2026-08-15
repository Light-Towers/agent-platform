"""extract_keywords 节点：LLM 抽取 + jieba/bigram 分词。"""

import json
from typing import Any

from wenda_data_agent.agent.llm import LLMClient


def _bigram_tokenize(text: str) -> list[str]:
    return [text[i : i + 2] for i in range(len(text) - 1)] if len(text) > 1 else [text]


def _jieba_tokenize(text: str) -> list[str]:
    try:
        import jieba

        return list(jieba.cut(text))
    except ImportError:
        return _bigram_tokenize(text)


async def extract_keywords(state: dict[str, Any]) -> dict[str, Any]:
    query = state.get("query", "")
    llm: LLMClient | None = state.get("llm")
    tokenizer: str = state.get("tokenizer", "bigram")

    keywords: list[str] = []
    if llm is not None and llm.enabled:
        prompt = f"从以下问题中抽取关键词，输出 JSON 数组：\n{query}"
        result = await llm.invoke(prompt)
        try:
            keywords = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            keywords = []

    tokens = _jieba_tokenize(query) if tokenizer == "jieba" else _bigram_tokenize(query)
    keywords = keywords or tokens
    return {"keywords": keywords}
