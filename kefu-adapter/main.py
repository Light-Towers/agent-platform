"""kefu-adapter：atguigu_ai REST 适配层。

atguigu_ai 已有 FastAPI server + /api/messages（POST）。
本适配器转发请求 → 转统一 QueryResponse schema → 返回给网关。

kefu 快照零改动（AGENTS.md 约束）。
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI

load_dotenv(find_dotenv())
logger = logging.getLogger(__name__)

KEFU_API_URL = os.getenv("KEFU_API_URL", "http://localhost:5005")
ADAPTER_VERSION = "0.1.0"

_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client
    _client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0))
    yield
    await _client.aclose()


app = FastAPI(title="kefu-adapter", version=ADAPTER_VERSION, lifespan=lifespan)


def _get_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("httpx client not initialized")
    return _client


@app.post("/query")
async def query(body: dict):
    """转发查询到 atguigu_ai /api/messages，返回 JSON。"""
    from shared_schemas import QueryData, QueryResponse

    start = time.perf_counter()
    client = _get_client()

    query_text = body.get("query", "")
    if not query_text:
        return QueryResponse(answer="", latency_ms=0.0).model_dump()

    session_id = body.get("session_id") or f"adapter-{uuid.uuid4().hex[:8]}"

    try:
        upstream_headers: dict[str, str] = {}
        try:
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "deepagents"))
            from agent.tracing.trace_propagation import inject_traceparent
            upstream_headers = inject_traceparent(upstream_headers)
        except Exception:
            logger.warning("traceparent 注入失败", exc_info=True)

        resp = await client.post(
            f"{KEFU_API_URL}/api/messages",
            json={"sender": session_id, "message": query_text},
            headers=upstream_headers,
        )
        latency = (time.perf_counter() - start) * 1000

        if resp.status_code != 200:
            return QueryResponse(
                answer=f"kefu 返回非 200: {resp.status_code}",
                fallback=True,
                latency_ms=latency,
            ).model_dump()

        messages = resp.json()
        answer_parts: list[str] = []
        buttons = None
        for msg in messages:
            text = msg.get("text")
            if text:
                answer_parts.append(text)
            if msg.get("buttons"):
                buttons = msg["buttons"]

        answer = "\n".join(answer_parts)
        data = QueryData(
            source="atguigu_ai",
            content={"buttons": buttons} if buttons else None,
            metadata={"session_id": session_id},
        )

        return QueryResponse(answer=answer, data=data, latency_ms=latency).model_dump()

    except httpx.ConnectError:
        return QueryResponse(
            answer="kefu 服务不可达",
            fallback=True,
            latency_ms=(time.perf_counter() - start) * 1000,
        ).model_dump()
    except Exception as e:
        return QueryResponse(
            answer=f"适配器内部错误: {e}",
            fallback=True,
            latency_ms=(time.perf_counter() - start) * 1000,
        ).model_dump()


@app.get("/health")
async def health():
    """健康检查：探活 atguigu_ai 后返回状态。"""
    from shared_schemas import DependencyHealth, HealthResponse, HealthStatus

    client = _get_client()
    deps: list[DependencyHealth] = []

    try:
        start = time.perf_counter()
        resp = await client.get(f"{KEFU_API_URL}/health", timeout=3.0)
        latency = (time.perf_counter() - start) * 1000
        deps.append(DependencyHealth(
            name="atguigu_ai",
            status=HealthStatus.HEALTHY if resp.status_code == 200 else HealthStatus.UNHEALTHY,
            latency_ms=latency,
        ))
    except Exception as e:
        deps.append(DependencyHealth(
            name="atguigu_ai",
            status=HealthStatus.UNHEALTHY,
            detail=str(e),
        ))

    overall = HealthStatus.HEALTHY if all(d.status == HealthStatus.HEALTHY for d in deps) else HealthStatus.UNHEALTHY
    return HealthResponse(status=overall, version=ADAPTER_VERSION, dependencies=deps).model_dump()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
