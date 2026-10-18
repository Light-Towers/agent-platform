"""extract_keywords 节点：LLM 抽取 + jieba/bigram 分词。

2026-10-18 审计（方案 P0-11⑤）：embedding 在这里算**一次**并写入
`state["query_embedding"]`，供三路召回共享。此前 column/metric 两个并行分支
各调一次 `embed_query(" ".join(keywords))`——同一输入双倍延迟与费用。
"""

import json
from typing import Any

from agent_core.logging import get_logger

from nl2sql_service.agent.llm import LLMClient
from nl2sql_service.tokenizer import bigram_tokenize, jieba_tokenize, tokenize

logger = get_logger(__name__)

# 兼容旧导入路径：分词实现已收敛到 nl2sql_service.tokenizer（写入侧同源）
_bigram_tokenize = bigram_tokenize
_jieba_tokenize = jieba_tokenize


async def extract_keywords(state: dict[str, Any]) -> dict[str, Any]:
    query = state.get("query", "")
    llm: LLMClient | None = state.get("llm")
    tokenizer: str = state.get("tokenizer", "bigram")

    keywords: list[str] = []
    llm_calls = 0
    if llm is not None and llm.enabled:
        prompt = f"从以下问题中抽取关键词，输出 JSON 数组：\n{query}"
        result = await llm.invoke(prompt)
        llm_calls = 1
        try:
            keywords = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            keywords = []

    tokens = tokenize(query, tokenizer)
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

    return {"keywords": keywords, "query_embedding": embedding, "llm_calls": state.get("llm_calls", 0) + llm_calls}
