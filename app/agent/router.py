"""意图路由：LLM 结构化决策，失败时回退确定性启发式。

启发式是评测基线（eval 门禁直接测它），也是 LLM 不可用时的兜底，
必须保持无副作用、可复现。
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.config import get_settings
from app.schemas import Capability

SQL_HINTS = ("sql", "数据库", "表里", "表中", "统计", "多少条", "多少笔", "销售额", "订单", "销量", "库存")
SEARCH_HINTS = ("最新", "最近", "新闻", "github", "趋势", "今天", "本周", "发布", "开源项目", "联网")
RAG_HINTS = ("知识库", "文档", "什么是", "解释", "原理", "怎么理解", "wiki", "笔记", "介绍")
MCP_HINTS = ("调用工具", "运行工具", "执行工具", "调用外部", "mcp", "调用 mcp")


class RouteDecision(BaseModel):
    capability: Literal["search", "rag", "sql", "direct", "mcp"] = Field(
        description="应调用的能力：search=联网搜索, rag=本地知识库, sql=数据库查询, direct=直接回答, mcp=外部工具"
    )
    sub_query: str = Field(description="传给子能力的关键查询词")
    reason: str = Field(description="一句话路由理由")


def heuristic_route(question: str) -> RouteDecision:
    """确定性关键词路由；优先级 mcp > sql > search > rag > direct。"""
    q = question.lower()
    if get_settings().mcp_enabled and any(h in q for h in MCP_HINTS):
        return RouteDecision(capability="mcp", sub_query=question, reason="命中外部工具调用特征词")
    if any(h in q for h in SQL_HINTS):
        return RouteDecision(capability="sql", sub_query=question, reason="命中数据查询特征词")
    if any(h in q for h in SEARCH_HINTS):
        return RouteDecision(capability="search", sub_query=question, reason="命中时效/联网特征词")
    if any(h in q for h in RAG_HINTS):
        return RouteDecision(capability="rag", sub_query=question, reason="命中知识库特征词")
    return RouteDecision(capability="direct", sub_query=question, reason="无明确能力特征")


async def decide_route(llm, question: str) -> RouteDecision:
    """LLM 结构化路由；任何异常回退启发式（绝不让路由失败阻塞主链路）。"""
    if llm is None:
        return heuristic_route(question)
    try:
        capabilities = "search=联网搜索, rag=本地知识库, sql=数据库查询, direct=直接回答"
        if get_settings().mcp_enabled:
            capabilities += ", mcp=调用外部工具"
        structured = llm.with_structured_output(RouteDecision)
        decision = await structured.ainvoke(
            [
                {"role": "system", "content": f"你是路由器。判断用户问题应走哪条能力链路：{capabilities}。"},
                {"role": "user", "content": question},
            ]
        )
        if isinstance(decision, RouteDecision):
            if decision.capability == "mcp" and not get_settings().mcp_enabled:
                return heuristic_route(question)
            return decision
    except Exception:  # noqa: BLE001 结构化失败回退启发式
        pass
    return heuristic_route(question)


def capability_label(cap: Capability) -> str:
    return {
        "search": "联网搜索",
        "rag": "知识库检索",
        "sql": "数据库查询",
        "direct": "直接回答",
        "mcp": "外部工具",
    }[cap]
