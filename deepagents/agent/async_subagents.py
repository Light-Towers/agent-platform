"""远程子 Agent 定义（AsyncSubAgent + Agent Protocol）。

D14：远程子服务以 subagent 形态包装（非裸 tool），
复用 task 委派 + monitor 链路。

子服务需实现 Agent Protocol（LangGraph Platform 原生支持，
FastAPI 服务用 langgraph-protocol 包适配）。
M2 阶段子服务尚未升级为 Agent Protocol server，
AGENT_MODE=local 时仍用本地 subagent。
"""

from __future__ import annotations

from deepagents import AsyncSubAgent

from agent.config import get_all_subservices
from agent.prompts import sub_agents_content


def _build_async_subagent(key: str, description: str) -> AsyncSubAgent:
    """构建单个 AsyncSubAgent。"""
    svc = get_all_subservices()[key]
    return AsyncSubAgent(
        graph_id=svc.graph_id,
        url=svc.url,
        name=svc.name,
        description=description,
    )


def get_remote_subagents() -> list[AsyncSubAgent]:
    """构建 3 个远程 AsyncSubAgent。

    text_to_sql → wenda-adapter（Text-to-SQL）
    rag_query   → zhiku（RAG 知识库）
    customer_service → kefu-adapter（客服）
    """
    return [
        _build_async_subagent(
            "text_to_sql",
            sub_agents_content["db"]["description"],
        ),
        _build_async_subagent(
            "rag_query",
            sub_agents_content["knowledge_base"]["description"],
        ),
        _build_async_subagent(
            "customer_service",
            "智能客服助手，处理订单查询、物流跟踪、售后退换等客服场景",
        ),
    ]
