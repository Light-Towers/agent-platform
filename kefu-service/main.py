"""kefu-service：从 atguigu_ai 迁移到 deepagents + LangGraph。

Phase 7：9 种命令 → LangGraph 意图路由，3 个 Flow → LangGraph 子图，
GraphRAG → 知识库检索子 Agent，atguigu_ai Tracker → LangGraph State。

运行：uvicorn main:app --host 0.0.0.0 --port 8003
"""

from __future__ import annotations

from fastapi import FastAPI

from agent.state import KefuState
from agent.graph import build_kefu_graph

app = FastAPI(title="kefu-service", version="0.1.0")

_kefu_graph = build_kefu_graph()


@app.get("/health")
async def health():
    return {"status": "ok", "service": "kefu-service", "phase": "7"}


@app.get("/health/live")
async def health_live():
    return {"status": "alive"}


@app.get("/health/ready")
async def health_ready():
    return {"status": "ready"}


@app.post("/api/messages")
async def handle_message(request: dict):
    """处理客服消息（对齐 atguigu_ai /api/messages 接口）。"""
    user_message = request.get("message", "")
    session_id = request.get("session_id", "default")
    tenant_id = request.get("tenant_id", "default")

    config = {"configurable": {"thread_id": session_id, "tenant_id": tenant_id}}
    initial_state: KefuState = {
        "user_message": user_message,
        "session_id": session_id,
        "tenant_id": tenant_id,
        "intent": None,
        "slots": {},
        "flow_state": None,
        "response": None,
        "history": [],
    }

    result = await _kefu_graph.ainvoke(initial_state, config=config)
    return {
        "answer": result.get("response", ""),
        "intent": result.get("intent"),
        "session_id": session_id,
    }
