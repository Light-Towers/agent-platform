"""wenda-adapter：SSE→JSON 适配层。

wenda `/api/query` 是 SSE 流式（text/event-stream），与联邦网关目标 JSON schema 不兼容。
本适配器消费 SSE 流 → 聚合为 QueryResponse JSON → 返回给网关。

wenda 快照零改动（AGENTS.md 约束）。
"""

from __future__ import annotations

import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI

load_dotenv(find_dotenv())

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


async def _consume_sse_stream(response: httpx.Response) -> tuple[str, dict | None, str | None]:
    """消费 SSE 流，聚合为 (answer, data, error)。

    wenda SSE 格式：`data: {json_chunk}\\n\\n`
    chunk 有 type 字段，最后一条通常是最终回答。
    """
    answer_parts: list[str] = []
    last_data: dict | None = None
    error_msg: str | None = None

    async for line in response.aiter_lines():
        if not line.startswith("data: "):
            continue
        payload = line[len("data: "):].strip()
        if not payload:
            continue
        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError:
            continue

        chunk_type = chunk.get("type", "")
        if chunk_type == "error":
            error_msg = chunk.get("message", "unknown error")
            break

        if chunk_type == "result":
            data = chunk.get("data")
            if isinstance(data, str) and data:
                answer_parts.append(data)
            elif isinstance(data, dict):
                text = data.get("answer") or data.get("content") or data.get("text") or ""
                if isinstance(text, str) and text:
                    answer_parts.append(text)
                last_data = data
            continue

        content = chunk.get("content") or chunk.get("answer") or chunk.get("text") or ""
        if isinstance(content, str) and content:
            answer_parts.append(content)

        if chunk_type in ("final", "answer", "complete"):
            last_data = chunk

    answer = "".join(answer_parts)
    return answer, last_data, error_msg


@app.post("/query")
async def query(body: dict):
    """转发查询到 wenda，消费 SSE 流，返回 JSON。"""
    from shared_schemas import QueryData, QueryResponse

    start = time.perf_counter()
    client = _get_client()

    query_text = body.get("query", "")
    if not query_text:
        return QueryResponse(answer="", latency_ms=0.0).model_dump()

    try:
        upstream_headers: dict[str, str] = {}
        try:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "deepagents"))
            from agent.tracing.trace_propagation import inject_traceparent
            upstream_headers = inject_traceparent(upstream_headers)
        except Exception:
            pass

        async with client.stream(
            "POST",
            f"{WENDA_API_URL}/api/query",
            json={"query": query_text},
            headers=upstream_headers,
        ) as resp:
            if resp.status_code != 200:
                return QueryResponse(
                    answer=f"wenda 返回非 200: {resp.status_code}",
                    fallback=True,
                    latency_ms=(time.perf_counter() - start) * 1000,
                ).model_dump()

            answer, data, error = await _consume_sse_stream(resp)

        latency = (time.perf_counter() - start) * 1000
        if error:
            return QueryResponse(
                answer=answer or "",
                data=QueryData(source="wenda", metadata={"error": error}),
                latency_ms=latency,
                fallback=True,
            ).model_dump()

        return QueryResponse(
            answer=answer,
            data=QueryData(source="wenda", content=data) if data else None,
            latency_ms=latency,
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
