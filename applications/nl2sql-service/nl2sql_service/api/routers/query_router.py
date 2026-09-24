"""POST /api/query 路由：Text-to-SQL 查询。"""

import time

from agent_core.logging import get_logger
from fastapi import APIRouter, HTTPException, Request

from nl2sql_service.api.schemas.query_schema import SqlQueryRequest, SqlQueryResponse

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["query"])


@router.post("/query", response_model=SqlQueryResponse)
async def query(request: SqlQueryRequest, http_request: Request) -> SqlQueryResponse:
    start = time.perf_counter()
    query_service = http_request.app.state.query_service

    try:
        result = await query_service.query(request.query, metric_config=request.metric_config)
        latency = (time.perf_counter() - start) * 1000
        return SqlQueryResponse(
            answer=result.get("answer", ""),
            sql=result.get("sql"),
            error=result.get("error"),
            fallback=result.get("fallback", False),
            latency_ms=round(latency, 2),
            trace_id=request.trace_id,
        )
    except Exception as exc:
        logger.exception("query handler failed")
        raise HTTPException(status_code=500, detail=f"Internal query error: {type(exc).__name__}") from exc
