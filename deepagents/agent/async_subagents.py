"""远程子 Agent 定义（AsyncSubAgent + Agent Protocol）。

D14：远程子服务以 subagent 形态包装（非裸 tool），
复用 task 委派 + monitor 链路。

子服务需实现 Agent Protocol（LangGraph Platform 原生支持，
FastAPI 服务用 langgraph-protocol 包适配）。
M2 阶段子服务尚未升级为 Agent Protocol server，
AGENT_MODE=local 时仍用本地 subagent。

远程调用实现说明（Phase 7 收尾已修复）：
  优先使用外部 `deepagents` 包的 `AsyncSubAgent`（graph_id+url，Agent Protocol）。
  若该包未安装（当前 .venv 未包含），自动回退到基于 httpx 的
  `_HttpSubAgent`：POST 到子服务各自的 endpoint（见 SubserviceConfig.endpoint），
  例如 kefu 直连走 /invoke（返回 QueryResponse），wenda-data-agent 走 /api/query
  （返回 SqlQueryResponse）。两路径对外暴露同一 `ainvoke(input)` 接口。
"""

from __future__ import annotations

from agent.config import get_all_subservices, use_kefu_adapter
from agent.prompts import sub_agents_content

try:  # 外部 deepagents 包（Agent Protocol 原生支持）
    from deepagents import AsyncSubAgent

    _HAS_DEEPAGENTS = True
except Exception:  # pragma: no cover - 回退路径
    AsyncSubAgent = None  # type: ignore[assignment]
    _HAS_DEEPAGENTS = False


import httpx


class _HttpSubAgent:
    """deepagents 未安装时的 httpx 远程回退（兼容 AsyncSubAgent.ainvoke 接口）。"""

    def __init__(self, svc, description: str) -> None:
        self.name = svc.name
        self.graph_id = svc.graph_id
        self.url = svc.url
        self.endpoint = svc.endpoint
        self.description = description

    async def ainvoke(self, input: dict) -> dict:
        endpoint = self.endpoint
        payload = {
            "query": input.get("query", input.get("message", "")),
            "session_id": input.get("session_id"),
            "tenant_id": input.get("tenant_id"),
            "trace_id": input.get("trace_id"),
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self.url.rstrip("/") + endpoint, json=payload)
            resp.raise_for_status()
            data = resp.json()
        # kefu /invoke 返回 QueryResponse(dict)；wenda-data-agent /api/query 返回 SqlQueryResponse(dict)；
        # 旧 adapter /api/messages 返回 list。统一规整为 {"answer": ...} 供 main_agent 消费。
        if isinstance(data, list):
            text = " ".join(msg.get("text", "") for msg in data if isinstance(msg, dict))
            return {"answer": text}
        if isinstance(data, dict):
            return {"answer": data.get("answer", ""), **data}
        return {"answer": str(data)}


def _build_async_subagent(key: str, description: str):
    """构建单个远程子 Agent（优先 AsyncSubAgent，否则 httpx 回退）。"""
    svc = get_all_subservices()[key]
    if _HAS_DEEPAGENTS and AsyncSubAgent is not None:
        return AsyncSubAgent(
            graph_id=svc.graph_id,
            url=svc.url,
            name=svc.name,
            description=description,
        )
    return _HttpSubAgent(svc, description)


def get_remote_subagents():
    """构建 3 个远程子 Agent。

    text_to_sql → wenda-data-agent(:8001)/api/query（Text-to-SQL，adapter 已退役）
    rag_query   → zhiku（RAG 知识库）
    customer_service → kefu-service(:8003)/invoke（直连）或 kefu-adapter(:8002)
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
