"""GraphRAG 子 Agent：对应 atguigu_ai information_retrieval.py 的 6 步流程。

6 步：实体抽取 → 关系构建 → 社区检测 → 检索 → 排序 → 生成
接入知识库（配置驱动，不依赖外部 Neo4j）。
"""

from __future__ import annotations

from typing import Any

from agent_core.logging import get_logger

logger = get_logger(__name__)

_KNOWLEDGE_BASE: dict[str, dict[str, Any]] = {
    "报销": {
        "entities": ["报销", "差旅费", "发票"],
        "content": "公司报销流程：1. 填写报销申请单 2. 附上发票原件 3. 部门主管审批 4. 财务审核 5. 打款。差旅费标准：经济舱/二等座，住宿一线城市 500/晚，其他城市 400/晚。",
    },
    "年假": {
        "entities": ["年假", "假期", "休假"],
        "content": "年假政策：工龄 1-10 年享有 5 天年假，10-20 年享有 10 天，20 年以上享有 15 天。需提前 3 天在 OA 系统申请。",
    },
    "报销流程": {
        "entities": ["报销", "流程", "审批"],
        "content": "报销流程：填写申请单 → 附发票 → 主管审批 → 财务审核 → 打款。一般 5-7 个工作日完成。",
    },
    "退换货": {
        "entities": ["退换货", "退款", "售后"],
        "content": "退换货政策：签收 7 天内可无理由退货，15 天内可换货。商品需保持原包装完好。质量问题运费由卖家承担。",
    },
    "考勤": {
        "entities": ["考勤", "打卡", "迟到"],
        "content": "考勤制度：工作日 9:00-18:00，弹性 30 分钟。迟到 3 次以内口头提醒，超过 3 次扣绩效。补卡需在 3 天内申请。",
    },
    "入职": {
        "entities": ["入职", "新员工", "办理"],
        "content": "入职流程：1. 提交材料（身份证/学历/银行卡）2. 签订劳动合同 3. 领取工牌 4. IT 配置电脑 5. 部门报到。",
    },
}


async def extract_entities(text: str) -> list[str]:
    """步骤 1：实体抽取（关键词匹配）。"""
    entities = []
    for key, entry in _KNOWLEDGE_BASE.items():
        for entity in entry["entities"]:
            if entity in text:
                entities.append(entity)
    entities = list(set(entities))
    logger.debug("实体抽取: %s → %s", text, entities)
    return entities


async def build_relations(entities: list[str]) -> list[dict[str, Any]]:
    """步骤 2：关系构建（实体共现关系）。"""
    relations = []
    for i, e1 in enumerate(entities):
        for e2 in entities[i + 1:]:
            relations.append({"source": e1, "target": e2, "type": "co_occurrence"})
    return relations


async def detect_communities(relations: list[dict[str, Any]]) -> list[list[str]]:
    """步骤 3：社区检测（连通分量）。"""
    if not relations:
        return []
    nodes: set[str] = set()
    for r in relations:
        nodes.add(r["source"])
        nodes.add(r["target"])
    return [list(nodes)]


async def retrieve(query: str, communities: list[list[str]]) -> list[dict[str, Any]]:
    """步骤 4：检索（从知识库匹配相关条目）。"""
    results = []
    for key, entry in _KNOWLEDGE_BASE.items():
        score = 0
        for entity in entry["entities"]:
            if entity in query:
                score += 1
        if score > 0:
            results.append({"key": key, "content": entry["content"], "score": score})
    return results


async def rank(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """步骤 5：排序（按 score 降序）。"""
    return sorted(results, key=lambda x: x["score"], reverse=True)


async def generate(query: str, ranked_results: list[dict[str, Any]]) -> str:
    """步骤 6：生成（拼接检索结果）。"""
    if not ranked_results:
        return "暂无相关信息，请尝试换个关键词描述您的问题。"
    parts = [f"关于「{query}」，为您找到以下信息：\n"]
    for i, r in enumerate(ranked_results[:3], 1):
        parts.append(f"{i}. {r['content']}")
    return "\n".join(parts)


async def graph_rag_query(query: str) -> str:
    """GraphRAG 完整 6 步流程。"""
    logger.info("GraphRAG 查询: %s", query)

    entities = await extract_entities(query)
    relations = await build_relations(entities)
    communities = await detect_communities(relations)
    results = await retrieve(query, communities)
    ranked = await rank(results)
    response = await generate(query, ranked)

    logger.info("GraphRAG 完成: entities=%d, results=%d", len(entities), len(ranked))
    return response
