"""extract_keywords 节点：LLM 抽取 + 共享检索分词（ADR-0017 / T8）。

2026-10-18 审计（方案 P0-11⑤）：embedding 在这里算**一次**并写入
`state["query_embedding"]`，供三路召回共享。此前 column/metric 两个并行分支
各调一次 `embed_query(" ".join(keywords))`——同一输入双倍延迟与费用。
"""

import json
from typing import Any

from agent_core.logging import get_logger
from agent_runtime.retrieval_tokenizer import get_tokenizer

from nl2sql_service.agent.llm import LLMClient

logger = get_logger(__name__)


async def extract_keywords(state: dict[str, Any]) -> dict[str, Any]:
    # 多轮（M3）：有改写则用 effective_query 抽词/算向量（召回承接上文意图），
    # 无则回落原始 query（单轮逐字节一致）。
    query = state.get("effective_query") or state.get("query", "")
    llm: LLMClient | None = state.get("llm")
    # tokenizer 仅作可追溯标记；实际分词实现与词典版本来自共享单例。
    tokenizer: str = state.get("tokenizer", "jieba")
    logger.info("nl2sql tokenization: impl=agent_runtime/retrieval_tokenizer dict_version=%s", get_tokenizer().dict_version)

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

    if tokenizer != "jieba":
        raise ValueError(f"不支持的分词器标记 {tokenizer!r}（ADR-0017 后仅 jieba 单源实现）")
    tokens = get_tokenizer().tokenize(query)
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
