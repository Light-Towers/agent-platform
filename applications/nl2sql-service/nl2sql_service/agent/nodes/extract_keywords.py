"""extract_keywords 节点：LLM 抽取 + jieba/bigram 分词。

2026-10-18 审计（方案 P0-11⑤）：embedding 在这里算**一次**并写入
`state["query_embedding"]`，供三路召回共享。此前 column/metric 两个并行分支
各调一次 `embed_query(" ".join(keywords))`——同一输入双倍延迟与费用。
"""

import json
from typing import Any

from agent_core.logging import get_logger

from nl2sql_service.agent.llm import LLMClient

logger = get_logger(__name__)

_jieba_warned = False


def _bigram_tokenize(text: str) -> list[str]:
    return [text[i : i + 2] for i in range(len(text) - 1)] if len(text) > 1 else [text]


def _jieba_tokenize(text: str) -> list[str]:
    global _jieba_warned
    try:
        import jieba

        return list(jieba.cut(text))
    except ImportError:
        if not _jieba_warned:
            # 不再静默降级：jieba 是可选 extra，缺包时记一次告警
            logger.warning("TOKENIZER=jieba 但未安装 jieba，已降级 bigram（pip install 'nl2sql-service[tokenizer]'）")
            _jieba_warned = True
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

    # 单次 embedding：三路召回共享；失败时置 None，召回节点自行降级（不影响关键词）
    embedding: list[float] | None = None
    ctx = state.get("context")
    embedder = getattr(ctx, "embedding_client", None) if ctx is not None else None
    if embedder is not None:
        try:
            embedding = await embedder.embed_query(" ".join(keywords))
        except Exception:  # noqa: BLE001 - 向量化失败只降级召回路，不阻断查询
            logger.warning("query embedding failed, recall falls back to fulltext", exc_info=True)
            embedding = None

    return {"keywords": keywords, "query_embedding": embedding}
