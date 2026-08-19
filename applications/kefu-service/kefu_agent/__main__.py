"""kefu-service：从 legacy 客服平台迁移到 deepagents + LangGraph。

Phase 7：9 种命令 → LangGraph 意图路由，3 个 Flow → LangGraph 子图，
GraphRAG → 知识库检索子 Agent，legacy tracker → LangGraph State。

运行：uvicorn kefu_agent:app --host 0.0.0.0 --port 8003

网关接入状态（已修复）：本服务已实现且 CI 通过，并已于 Phase 7 收尾补齐：
  - 接入 shared-schemas 统一契约，新增 `POST /invoke`（Agent Protocol 兼容，
    接受 graph_id + input，返回 QueryResponse），供 deepagents 联邦网关远程直连；
  - `POST /api/messages` 保留为 legacy 兼容入口（旧契约），内部复用统一核心逻辑；
  - agent_federation/agent/config.py 新增 KEFU_SERVICE_URL + KEFU_USE_ADAPTER 开关，
    置 KEFU_USE_ADAPTER=false 即直连本服务；kefu-adapter 转换层已于 2026-08 移除
    （legacy 接入层退役由运维执行）。
"""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver
from shared_schemas import QueryRequest, QueryResponse
from shared_schemas.query import QueryData

from kefu_agent.graph import build_kefu_graph
from kefu_agent.state import KefuState

logger = logging.getLogger(__name__)

app = FastAPI(title="kefu-service", version="0.1.0")

_kefu_graph = build_kefu_graph(checkpointer=InMemorySaver())


@app.get("/health")
async def health():
    return {"status": "ok", "service": "kefu-service", "phase": "7"}


@app.get("/health/live")
async def health_live():
    return {"status": "alive"}


@app.get("/health/ready")
async def health_ready():
    return {"status": "ready"}


async def _run_kefu(req: QueryRequest) -> QueryResponse:
    """统一核心：QueryRequest → QueryResponse（U-1 契约统一）。"""
    t0 = time.perf_counter()
    session_id = req.session_id or "default"
    tenant_id = req.tenant_id or "default"

    config = {"configurable": {"thread_id": session_id, "tenant_id": tenant_id}}
    initial_state: KefuState = {
        "user_message": req.query,
        "session_id": session_id,
        "tenant_id": tenant_id,
    }

    result = await _kefu_graph.ainvoke(initial_state, config=config)
    answer = result.get("response", "") or ""
    intent = result.get("intent")
    latency_ms = round((time.perf_counter() - t0) * 1000, 2)

    # 契约语义增强（TB-6）：answer 为空属于"形状合法但内容空洞"退化，显式告警便于观测。
    if not answer or not answer.strip():
        logger.warning(
            "kefu 响应 answer 为空（意图=%s），疑似图未产出 response，将返回空回答", intent
        )

    return QueryResponse(
        answer=answer,
        data=QueryData(content={"intent": intent}, source="kefu-service"),
        trace_id=req.trace_id,
        latency_ms=latency_ms,
        intent=intent,
        # 显式标注未走降级路径，增强联邦契约符合性可见性（默认 False 但显式表达语义）
        fallback=False,
    )


@app.post("/invoke")
async def invoke(req: QueryRequest):
    """Agent Protocol 兼容入口（graph_id 预留，供联邦网关远程直连）。

    agent_federation/agent/async_subagents.py 在 KEFU_USE_ADAPTER=false 时经
    KEFU_SERVICE_URL(:8003)/invoke 调用本端点，返回 QueryResponse。
    """
    # graph_id 当前仅 kefu-service 单图，预留供扩展多图路由
    return await _run_kefu(req)


@app.post("/api/messages")
async def handle_message(request: dict):
    """处理客服消息（对齐 legacy /api/messages 接口，旧契约保留）。"""
    req = QueryRequest(
        query=request.get("message", ""),
        session_id=request.get("session_id", "default"),
        tenant_id=request.get("tenant_id", "default"),
    )
    resp = await _run_kefu(req)
    # 对齐 legacy 契约：返回 List[MessageResponse]（list-of-{text,buttons}）
    # kefu-adapter 期望 list-of-{text}，dict 会被 for msg in dict 迭代 keys(str) 导致 AttributeError。
    messages = []
    if resp.answer:
        messages.append({"recipient_id": req.session_id, "text": resp.answer})
    if resp.intent:
        # 将意图信息附带在 custom 字段，适配器忽略但不崩溃
        if messages:
            messages[0]["custom"] = {"intent": resp.intent}
        else:
            messages.append(
                {"recipient_id": req.session_id, "text": "", "custom": {"intent": resp.intent}}
            )
    return messages
