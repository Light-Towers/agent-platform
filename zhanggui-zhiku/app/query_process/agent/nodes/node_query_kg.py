# -*- coding: utf-8 -*-
"""
知识图谱检索节点（zhanggui-zhiku）。

从原先的 time.sleep(1) stub 落地为真实 Neo4j 实体/关系检索：
- 取 state 的 rewritten_query / item_names，调用 neo4j_utils.query_kg；
- 结果格式化为 kg_chunks（与向量召回同构：chunk_id/content/item_name/score），
  经 wrap_channel_node 写入 state["kg_chunks"]，汇入 node_rrf → node_rerank；
- Neo4j 未配置 / 空库 / 查询异常时降级为空，不阻断主链路。

依赖：app.clients.neo4j_utils（Neo4j 驱动惰性初始化）。
"""

from agent_core.logging import get_logger
from agent_core.tracing import traced_span
from app.clients.neo4j_utils import query_kg
from app.conf.retrieval_config import retrieval_cfg

logger = get_logger(__name__)

_NODE_NAME = "node_query_kg"


def _kg_span_attrs(*args, result=None, **kwargs):
    """retrieval.kg span 动态属性（KG 增强通道，诚实反映命中数）。"""
    result = result or {}
    kg_docs = result.get("kg_chunks") or [] if isinstance(result, dict) else []
    return {
        "hits": len(kg_docs),
        "timeout_s": retrieval_cfg.channels.kg.timeout_s,
    }


@traced_span("retrieval.kg", attributes_fn=_kg_span_attrs)
def node_query_kg(state: dict) -> dict:
    """KG 检索节点：返回 {"kg_chunks": [...]} 写入 state["kg_chunks"]。

    Args:
        state: 检索工作流状态（含 rewritten_query / item_names）。

    Returns:
        {"kg_chunks": [...]} —— 无命中时为空列表。
    """
    rewritten = state.get("rewritten_query") or state.get("original_query") or ""
    item_names = state.get("item_names") or None

    kg_docs = []
    if rewritten:
        try:
            kg_docs = query_kg(rewritten, item_names=item_names, limit=8)
        except Exception as e:
            logger.warning("KG 检索异常，跳过: %s", e)
            kg_docs = []
    else:
        logger.debug("rewritten_query 为空，KG 检索跳过")

    if kg_docs:
        logger.info(f"KG 检索命中 {len(kg_docs)} 条")
    else:
        logger.debug("KG 检索无命中（Neo4j 未配置/空库/无匹配），降级为空")

    return {"kg_chunks": kg_docs}
