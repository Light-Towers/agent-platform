"""HTTP 端点：/health、/query(SSE)、/import、/sql/train、/session/revert。"""

import json
import logging
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.api.auth import resolve_thread_id, verify_api_key
from app.config import get_settings
from app.infra import cache as semantic_cache
from app.infra.db import get_pool, ping
from app.infra.otel import get_otel_tracer, parse_traceparent, redact_question
from app.rag.chunker import split_markdown
from app.rag.embed import embed_query
from app.rag.store import add_document
from app.schemas import (
    AdmissionDecision,
    HealthResponse,
    ImportResponse,
    Priority,
    QueryRequest,
    RevertRequest,
    RevertResponse,
    SqlTrainRequest,
    SqlTrainResponse,
)
from app.sql.guard import detect_dialect
from app.sql.schema_store import store_ddl, store_doc, store_example

logger = logging.getLogger(__name__)
router = APIRouter()

_TEXT_SUFFIXES = {".md", ".markdown", ".txt"}


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    db_ok = await ping() if settings.db_enabled else False
    status = "ok" if (db_ok or not settings.db_enabled) else "degraded"
    return HealthResponse(
        status=status,
        storage="postgres" if settings.db_enabled else "memory",
        llm=settings.llm_enabled,
        search=bool(settings.search_api_key),
        sql_backend=detect_dialect(settings.sql_dsn) if settings.sql_dsn else "none",
        coordination=settings.coordination_enabled,
        admission=settings.admission_effective_enabled,
        revert=settings.revert_enabled,
        otel=settings.otel_effective_enabled,
        mcp=settings.mcp_enabled,
    )


@router.post("/query")
async def query(
    req: QueryRequest,
    request: Request,
    api_key=Depends(verify_api_key),
    x_priority: str | None = Header(default=None, alias="X-Priority"),
    traceparent: str | None = Header(default=None),
):
    settings = get_settings()
    thread_id = resolve_thread_id(req.thread_id, api_key)
    graph = request.app.state.graph
    pool = get_pool()

    # priority 来源优先级：X-Priority header > req.priority body > 默认 normal
    priority: Priority = "normal"
    if x_priority in ("high", "normal", "low"):
        priority = x_priority
    elif req.priority in ("high", "normal", "low"):
        priority = req.priority

    request_id = str(uuid.uuid4())

    # Phase 2: durable admission 前置
    decision = None
    admission_queue = getattr(request.app.state, "admission_queue", None)
    if admission_queue is not None and settings.admission_effective_enabled:
        decision = await admission_queue.enqueue(
            request_id, thread_id, req.user_id, priority
        )
        if decision.status == "rejected":
            raise HTTPException(
                status_code=429 if decision.reason == "RATE_LIMITED" else 503,
                detail=decision.reason or "ADMISSION_REJECTED",
            )

    # Phase 2: 会话并发协调前置
    coordinator = getattr(request.app.state, "coordinator", None)
    coord_decision = None
    if coordinator is not None and settings.coordination_enabled:
        coord_decision = await coordinator.acquire(thread_id, request_id)
        if coord_decision.decision_type == "reject":
            raise HTTPException(status_code=409, detail="CONCURRENCY_REJECTED")

    # Phase 2: OTel traceparent 透传
    otel_ctx = parse_traceparent(traceparent)
    otel_tracer = getattr(request.app.state, "otel_tracer", None)

    # 语义缓存：命中直接返回
    q_embedding: list[float] | None = None
    if settings.cache_enabled and pool is not None:
        q_embedding = await embed_query(req.question)
        cached = await semantic_cache.cache_lookup(pool, q_embedding, settings.cache_threshold)
        if cached:
            async def _cached_stream():
                yield _sse({"type": "cache_hit", "text": cached})
                yield _sse({"type": "done", "thread_id": thread_id})

            return StreamingResponse(_cached_stream(), media_type="text/event-stream")

    config = {"configurable": {"thread_id": thread_id}}

    async def _stream():
        # Phase 2: admission queued 前置事件（复用外层 decision，避免重复入队）
        if (
            admission_queue is not None
            and settings.admission_effective_enabled
            and decision is not None
            and decision.status == "queued"
        ):
            yield _sse({
                "type": "admission",
                "status": "queued",
                "position": decision.queue_position,
            })
        # Phase 2: coordination queue 前置事件
        if coord_decision is not None and coord_decision.decision_type == "queue":
            yield _sse({"type": "coordination", "decision": "queue"})
            await coordinator.wait_for_turn(thread_id, request_id)

        # Phase 2: OTel request span
        span = None
        if otel_tracer is not None:
            span = otel_tracer.start_as_current_span("query")
            span.__enter__()
            span.set_attribute("thread_id", thread_id)
            span.set_attribute("priority", priority)
            for k, v in redact_question(req.question).items():
                span.set_attribute(k, v)

        try:
            final_answer = ""
            async for update in graph.astream(
                {"messages": [("user", req.question)], "question": req.question,
                 "user_id": req.user_id, "iterations": 0},
                config=config,
                stream_mode="updates",
            ):
                for node, payload in update.items():
                    event = _node_event(node, payload)
                    if event:
                        yield _sse(event)
                    if node == "synthesize" and payload.get("answer"):
                        final_answer = payload["answer"]
            if final_answer and q_embedding is not None:
                semantic_cache.cache_store(pool, req.question, final_answer, q_embedding)
            yield _sse({"type": "done", "thread_id": thread_id, "answer": final_answer})
        finally:
            if span is not None:
                span.__exit__(None, None, None)
            # Phase 2: coordination release
            if coordinator is not None and settings.coordination_enabled:
                await coordinator.release(thread_id, request_id)
            # Phase 2: admission mark completed
            if admission_queue is not None and settings.admission_effective_enabled:
                await admission_queue.mark_completed(request_id)

    return StreamingResponse(_stream(), media_type="text/event-stream")


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _node_event(node: str, payload: dict) -> dict | None:
    if node == "route":
        return {
            "type": "route",
            "capability": payload.get("route"),
            "reason": payload.get("route_reason"),
        }
    if node in ("search", "rag", "sql", "mcp"):
        evidence = payload.get("evidence", [])
        return {"type": "evidence", "node": node, "count": len(evidence),
                "preview": evidence[0][:200] if evidence else ""}
    if node == "synthesize" and payload.get("answer"):
        return {"type": "answer", "text": payload["answer"]}
    return None


@router.post("/import", response_model=ImportResponse)
async def import_document(file: UploadFile, api_key=Depends(verify_api_key)):
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="知识库未启用（DATABASE_URL 未配置）")
    filename = file.filename or "upload"
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    raw = await file.read()

    if suffix in _TEXT_SUFFIXES:
        text = raw.decode("utf-8", errors="replace")
    elif suffix == ".pdf":
        text = _extract_pdf(raw)
    else:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {suffix or '未知'}")

    chunks = split_markdown(text)
    if not chunks:
        raise HTTPException(status_code=400, detail="文档内容为空或无法切分")
    doc_id = await add_document(pool, source=filename, chunks=chunks)
    return ImportResponse(doc_id=doc_id, source=filename, chunks=len(chunks))


def _extract_pdf(raw: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise HTTPException(
            status_code=400, detail="PDF 支持需安装可选依赖: pip install agent-platform[pdf]"
        ) from exc
    import io

    reader = PdfReader(io.BytesIO(raw))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


@router.post("/sql/train", response_model=SqlTrainResponse)
async def sql_train(req: SqlTrainRequest, api_key=Depends(verify_api_key)):
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="训练数据存储未启用（DATABASE_URL 未配置）")
    resp = SqlTrainResponse()
    if req.ddl:
        await store_ddl(pool, req.ddl)
        resp.ddl_stored = True
    if req.documentation:
        await store_doc(pool, req.documentation)
        resp.doc_stored = True
    if req.question and req.sql:
        await store_example(pool, req.question, req.sql)
        resp.example_stored = True
    if not (resp.ddl_stored or resp.doc_stored or resp.example_stored):
        raise HTTPException(
            status_code=400, detail="至少提供 ddl / documentation / (question+sql) 之一"
        )
    return resp


@router.post("/session/revert", response_model=RevertResponse)
async def session_revert(
    req: RevertRequest,
    request: Request,
    api_key=Depends(verify_api_key),
):
    settings = get_settings()
    if not settings.revert_enabled:
        raise HTTPException(status_code=404, detail="REVERT_NOT_ENABLED")

    revert_handler = getattr(request.app.state, "revert_handler", None)
    if revert_handler is None:
        raise HTTPException(status_code=404, detail="REVERT_NOT_INITIALIZED")

    operator = api_key or "default"
    result = await revert_handler.revert(operator, req.session_id, req.checkpoint_id)

    if not result.success:
        if result.error == "CHECKPOINT_NOT_FOUND":
            raise HTTPException(status_code=404, detail="CHECKPOINT_NOT_FOUND")
        if result.error == "FORBIDDEN":
            raise HTTPException(status_code=403, detail="FORBIDDEN")
        raise HTTPException(status_code=500, detail=result.error or "REVERT_FAILED")

    from datetime import datetime, timezone

    return RevertResponse(
        session_id=result.session_id,
        checkpoint_id=result.checkpoint_id,
        context_summary=result.context_summary,
        reverted_at=datetime.now(timezone.utc).isoformat(),
    )
