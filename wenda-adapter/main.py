"""wenda-adapter：JSON 转发适配层。

wenda-data-agent `/api/query` 返回 SqlQueryResponse JSON，本适配器转发并映射为
联邦网关 QueryResponse JSON 契约。

wenda 快照零改动（AGENTS.md 约束）。
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager

import httpx
from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI

load_dotenv(find_dotenv())
logger = logging.getLogger(__name__)

# WENDA_API_URL 默认指向 wenda-data-agent 生产服务（端口 8000）。
# 可通过环境变量覆盖回退课程快照。
WENDA_API_URL = os.getenv("WENDA_API_URL", "http://localhost:8000")
ADAPTER_VERSION = "0.1.0"

_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client
    _client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0))
    yield
    await _client.aclose()


app = FastAPI(title="wenda-adapter", version=ADAPTER_VERSION, lifespan=lifespan)


def _get_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("httpx client not initialized")
    return _client


@app.post("/query")
async def query(body: dict):
    """转发查询到 wenda-data-agent，返回 JSON。"""
    from shared_schemas import QueryData, QueryResponse

    start = time.perf_counter()
    client = _get_client()

    query_text = body.get("query", "")
    if not query_text:
        return QueryResponse(answer="", latency_ms=0.0).model_dump()

    try:
        upstream_headers: dict[str, str] = {}
        try:
            from agent_core.tracing_propagation import inject_traceparent
            upstream_headers = inject_traceparent(upstream_headers)
        except Exception:
            logger.warning("traceparent 注入失败", exc_info=True)

        resp = await client.post(
            f"{WENDA_API_URL}/api/query",
            json={"query": query_text},
            headers=upstream_headers,
        )

        latency = (time.perf_counter() - start) * 1000

        if resp.status_code != 200:
            return QueryResponse(
                answer=f"wenda 返回非 200: {resp.status_code}",
                fallback=True,
                latency_ms=latency,
            ).model_dump()

        payload = resp.json()
        answer = payload.get("answer", "")
        error = payload.get("error")
        data_dict = payload.get("data")

        if error:
            return QueryResponse(
                answer=answer,
                data=QueryData(source="wenda", metadata={"error": error}),
                latency_ms=latency,
                fallback=payload.get("fallback", True),
            ).model_dump()

        return QueryResponse(
            answer=answer,
            data=QueryData(source="wenda", content=data_dict) if data_dict else None,
            latency_ms=latency,
            fallback=payload.get("fallback", False),
        ).model_dump()

    except httpx.ConnectError:
        return QueryResponse(
            answer="wenda 服务不可达",
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
    """健康检查：探活 wenda 后返回状态。"""
    from shared_schemas import DependencyHealth, HealthResponse, HealthStatus

    client = _get_client()
    deps: list[DependencyHealth] = []

    try:
        start = time.perf_counter()
        resp = await client.get(f"{WENDA_API_URL}/", timeout=3.0)
        latency = (time.perf_counter() - start) * 1000
        deps.append(DependencyHealth(
            name="wenda",
            status=HealthStatus.HEALTHY if resp.status_code < 500 else HealthStatus.UNHEALTHY,
            latency_ms=latency,
        ))
    except Exception as e:
        deps.append(DependencyHealth(
            name="wenda",
            status=HealthStatus.UNHEALTHY,
            detail=str(e),
        ))

    overall = HealthStatus.HEALTHY if all(d.status == HealthStatus.HEALTHY for d in deps) else HealthStatus.UNHEALTHY
    return HealthResponse(status=overall, version=ADAPTER_VERSION, dependencies=deps).model_dump()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
