"""HTTP 端点：/health、/query(SSE)、/import、/sql/train、/session/revert。"""

import json
import logging
import uuid
from datetime import UTC

from agent_core.runtime.lease import AsyncLease
from agent_runtime import cache as semantic_cache
from agent_runtime.db import get_pool, ping
from agent_runtime.otel import redact_question
from agent_runtime.planner.protocol import PlannerContext
from fastapi import APIRouter, Depends, Header, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from agent_server.api.auth import resolve_thread_id, verify_api_key
from agent_server.config import get_settings
from agent_server.memory import thread_persist as _thread_persist
from agent_server.rag.chunker import split_markdown
from agent_server.rag.embed import embed_query
from agent_server.rag.store import add_document
from agent_server.schemas import (
    HealthResponse,
    ImportResponse,
    Priority,
    QueryRequest,
    RevertRequest,
    RevertResponse,
    SqlTrainRequest,
    SqlTrainResponse,
)
from agent_server.sql.guard import detect_dialect
from agent_server.sql.schema_store import store_ddl, store_doc, store_example

logger = logging.getLogger(__name__)
router = APIRouter()

_TEXT_SUFFIXES = {".md", ".markdown", ".txt"}


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    from shared_schemas import HealthStatus

    settings = get_settings()
    db_ok = await ping() if settings.db_enabled else False
    status = HealthStatus.HEALTHY if (db_ok or not settings.db_enabled) else HealthStatus.DEGRADED
    return HealthResponse(
        status=status,
        version="0.1.0",
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
    thread_id = resolve_thread_id(req.session_id, api_key)
    graph = request.app.state.graph
    planner = getattr(request.app.state, "planner", None)
    planner_runtime = getattr(request.app.state, "planner_runtime", None)
    checkpointer = getattr(request.app.state, "checkpointer", None)
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

    # 统一生命周期租约（幂等）。覆盖所有退出路径：coordinator reject、cache hit、
    # 正常完成、graph 异常、客户端断开、排队后拒绝。无论哪条路径都必须经过它，
    # 否则 coordinator 槽位 / admission 容量会泄漏（审计 P0: #一 #二）。
    # AsyncLease 结构性保证幂等：release() 只执行一次，单个回调异常不影响其余
    # （异常隔离），替代手写 try/finally + bool 守卫。
    lease = AsyncLease()
    if coordinator is not None and settings.coordination_enabled:
        # release 处理已 active 的请求；cancel 确保本请求若仍在队列中
        # （排队中、尚未 active）也被清出，避免死请求被 promote 卡死会话
        # （审计 P1 #四：coordinator queue cancellation）。
        lease.on_release(lambda: coordinator.release(thread_id, request_id))
        if hasattr(coordinator, "cancel"):
            lease.on_release(lambda: coordinator.cancel(thread_id, request_id))
    if admission_queue is not None and settings.admission_effective_enabled:
        lease.on_release(lambda: admission_queue.mark_completed(request_id))

    if coordinator is not None and settings.coordination_enabled:
        coord_decision = await coordinator.acquire(thread_id, request_id)
        if coord_decision.decision_type == "reject":
            # 统一清理：coordinator.acquire 已占用 active/queued 槽位，reject 必须
            # 释放，否则该 session 的 coordination 容量永久少 1（P0: leak on reject）。
            # admission 已在前面 enqueue 并可能 admitted，同样要 mark_completed。
            await lease.release()
            raise HTTPException(status_code=409, detail="CONCURRENCY_REJECTED")

    # Phase 2: OTel tracer
    otel_tracer = getattr(request.app.state, "otel_tracer", None)

    # 语义缓存：命中直接返回。命中是正常路径，但 coordinator.acquire 已占用槽位、
    # admission 已可能 admitted —— 必须在返回前统一清理，否则同 session 后续请求
    # 会永久排队（P0: cache-hit leak）。
    q_embedding: list[float] | None = None
    if settings.cache_enabled and pool is not None:
        q_embedding = await embed_query(req.query)
        cached = await semantic_cache.cache_lookup(pool, q_embedding, settings.cache_threshold)
        if cached:
            await lease.release()

            async def _cached_stream():
                yield _sse({"type": "cache_hit", "text": cached})
                yield _sse({"type": "done", "thread_id": thread_id})

            return StreamingResponse(_cached_stream(), media_type="text/event-stream")

    config = {"configurable": {"thread_id": thread_id}}

    async def _stream():
        # decision 定义在 query() 作用域，闭包内需写回它（否则闭包内存在
        # 赋值即被视为局部变量，导致 queued 分支未触发时读取未初始化局部变量
        # → UnboundLocalError F823）。
        nonlocal decision
        # Phase 2: admission 排队阻塞等待（路径一：queued 时真正等待补位唤醒）
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
            decision = await admission_queue.wait_for_admit(request_id)
        if decision is not None and decision.status == "rejected":
            yield _sse({
                "type": "admission",
                "status": "rejected",
                "reason": decision.reason,
            })
            # 统一清理：_states[rid] 残留 "rejected" 且 DB 行仍是 "queued" →
            # count(admitted+queued) 永久含该记录，容量泄漏，直到进程重启
            # recover_on_startup 才清。mark_completed 会 pop 内存状态并把 DB 行
            # 标 completed，释放容量。走 lease.release() 统一出口，避免与外层重复清理。
            await lease.release()
            return
        if decision is not None and decision.status == "admitted":
            yield _sse({
                "type": "admission",
                "status": "admitted",
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
            for k, v in redact_question(req.query).items():
                span.set_attribute(k, v)

        try:
            final_answer = ""
            if planner is None or planner_runtime is None:
                # 兜底：Planner 未装配（理论不发生，lifespan 保证），走 graph 静态 DAG。
                async for update in graph.astream(
                    {"messages": [("user", req.query)], "question": req.query,
                     "user_id": req.user_id, "workspace_id": req.workspace_id,
                     "iterations": 0},
                    config=config,
                    stream_mode="updates",
                ):
                    for node, payload in update.items():
                        event = _node_event(node, payload)
                        if event:
                            yield _sse(event)
                        if node == "synthesize" and payload.get("answer"):
                            final_answer = payload["answer"]
            else:
                # Phase 3: 统一出口——编排权移交 Planner（plan 决策 + execute 编排），
                # 事件流经 StreamEvent 直通 SSE（与 graph 路径事件同构）。
                ctx = PlannerContext(
                    question=req.query,
                    workspace_id=req.workspace_id,
                    user_id=req.user_id,
                    messages=await _thread_persist.read_thread_messages(checkpointer, thread_id),
                    llm=planner_runtime.llm,
                )
                plan = await planner.plan(ctx)
                async for event in planner.execute(plan, planner_runtime):
                    sse = _stream_event(event)
                    if sse:
                        yield _sse(sse)
                    if event.type == "answer":
                        final_answer = event.payload.get("text", "")
            if final_answer and q_embedding is not None:
                semantic_cache.cache_store(pool, req.query, final_answer, q_embedding)
            # Phase 3: 对话历史写回——Planner 协议中立（不持线程语义），由 app 层承担。
            # 与 graph 路径的 checkpoint 持久化行为等价，/history 与 revert 不回退。
            if final_answer and checkpointer is not None:
                await _thread_persist.append_thread(checkpointer, thread_id, req.query, final_answer)
            yield _sse({"type": "done", "thread_id": thread_id, "answer": final_answer})
        finally:
            if span is not None:
                span.__exit__(None, None, None)
            # Phase 2: 统一生命周期清理（幂等，覆盖 graph 异常 / 客户端断开 /
            # 正常完成）。reject 与 cache-hit 路径已在 _stream 外提前调用过，
            # 此处再调用安全无副作用（AsyncLease 幂等）。
            await lease.release()

    return StreamingResponse(_stream(), media_type="text/event-stream")


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# 优化 I：精确回忆接口——按 thread_id 回溯历史对话原文（与 H 语义回忆正交）。
# 复用 app.state.checkpointer（LangGraph AsyncPostgresSaver，内核 get_checkpointer 工厂产出）。
from agent_server.memory import recall_exact as _recall_exact
from agent_server.schemas import HistoryItem, HistoryResponse


@router.get("/history", response_model=HistoryResponse)
async def history(
    session_id: str,
    keyword: str | None = None,
    limit: int | None = None,
    request: Request = None,
    api_key=Depends(verify_api_key),
):
    """精确回忆：按会话 thread_id 取回历史对话原文（优化 I）。

    与 /query 的语义召回（优化 H）正交：此处返回字面原文，支持关键词过滤，
    用于「找到我之前某次聊天里具体说了什么」。需 api_key 鉴权。
    """
    from agent_server.api.auth import resolve_thread_id

    thread_id = resolve_thread_id(session_id, api_key)
    checkpointer = getattr(request.app.state, "checkpointer", None)
    if checkpointer is None:
        raise HTTPException(status_code=503, detail="CHECKPOINTER_UNAVAILABLE")
    items = await _recall_exact.get_thread_history(
        checkpointer, thread_id, keyword=keyword, limit=limit
    )
    return HistoryResponse(
        thread_id=thread_id,
        count=len(items),
        items=[HistoryItem(**it) for it in items],
    )


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


def _stream_event(event) -> dict | None:
    """StreamEvent（Planner 协议）→ SSE 事件（与 graph 路径事件同构，客户端无感）。

    委托 ``serialize_stream_event``（agent_runtime 共享映射），app 与联邦双轨出口同源，
    避免 schema 漂移（Plan-F WS 出口统一）。
    """
    from agent_runtime.planner.protocol import serialize_stream_event

    return serialize_stream_event(event)


@router.post("/import", response_model=ImportResponse)
async def import_document(
    file: UploadFile,
    workspace_id: str = "default",
    api_key=Depends(verify_api_key),
):
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
    doc_id = await add_document(pool, source=filename, chunks=chunks, workspace_id=workspace_id)
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

    from datetime import datetime

    return RevertResponse(
        session_id=result.session_id,
        checkpoint_id=result.checkpoint_id,
        context_summary=result.context_summary,
        reverted_at=datetime.now(UTC).isoformat(),
    )
