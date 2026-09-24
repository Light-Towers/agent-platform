"""查询路由（SSE 流式）：/query。"""

import logging
import uuid

from agent_core.runtime.lease import AsyncLease
from agent_runtime import cache as semantic_cache
from agent_runtime.db import get_pool
from agent_runtime.otel import redact_question
from agent_runtime.planner.protocol import PlannerContext
from agent_runtime.schemas import ADMISSION_ADMITTED, ADMISSION_QUEUED, ADMISSION_REJECTED
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from shared_schemas import sse_pack

from agent_server.api.auth import resolve_thread_id, verify_api_key
from agent_server.config import get_settings
from agent_server.memory import thread_persist as _thread_persist
from agent_server.rag.embed import embed_query
from agent_server.schemas import Priority, QueryRequest

logger = logging.getLogger(__name__)
router = APIRouter()


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
    scheduler = getattr(request.app.state, "scheduler", None)
    status_store = getattr(request.app.state, "status_store", None)
    cost_governance = getattr(request.app.state, "cost_governance", None)

    # priority 来源优先级：X-Priority header > req.priority body > 默认 normal
    priority: Priority = "normal"
    if x_priority in ("high", "normal", "low"):
        priority = x_priority
    elif req.priority in ("high", "normal", "low"):
        priority = req.priority

    request_id = str(uuid.uuid4())

    # V3 Phase 2: ExecutionScheduler 入队（opt-in，未启用时跳过）
    # Admission 回答"允不允许"，Scheduler 叠加回答"什么时候执行"——两者不互斥
    scheduler_enqueued = False
    if scheduler is not None:
        from agent_runtime.execution_scheduler import ExecutionPriority, ExecutionRequest

        sched_priority = ExecutionPriority.NORMAL
        if priority == "high":
            sched_priority = ExecutionPriority.HIGH
        elif priority == "low":
            sched_priority = ExecutionPriority.LOW
        # P0-1（方案 B）：submit 入队（backpressure）；真正的并发门控在下方返回流之前
        # 经 try_start 认领专属槽位完成（超并发 → 503）。
        try:
            await scheduler.submit(ExecutionRequest(
                execution_id=request_id,
                tenant_id=req.tenant_id or "default",
                session_id=thread_id,
                user_id=req.user_id,
                priority=sched_priority,
            ))
            scheduler_enqueued = True
        except Exception:
            logger.warning("scheduler submit failed, continuing without queue", exc_info=True)
            scheduler = None

    # V3 Phase 4: Cost Governance check（opt-in，超限返回 429）
    if cost_governance is not None:
        from agent_runtime.cost_governance import BudgetDimension, BudgetExceeded

        _tenant = req.tenant_id or "default"
        try:
            await cost_governance.check(_tenant, BudgetDimension.REQUESTS, estimated_amount=1)
        except BudgetExceeded:
            raise HTTPException(status_code=429, detail="BUDGET_EXCEEDED")

    # Phase 2: durable admission 前置
    decision = None
    admission_controller = getattr(request.app.state, "admission_controller", None)
    if admission_controller is not None and settings.admission_effective_enabled:
        decision = await admission_controller.enqueue(
            request_id, thread_id, req.user_id, priority
        )
        if decision.status == ADMISSION_REJECTED:
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
    if admission_controller is not None and settings.admission_effective_enabled:
        lease.on_release(lambda: admission_controller.mark_completed(request_id))

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
        cached = await semantic_cache.cache_lookup(pool, q_embedding, settings.cache_threshold, tenant_id=req.tenant_id or "")
        if cached:
            await lease.release()
            # P0-1（方案 B）：cache-hit 从未经 try_start 认领，但 submit 已留下 QUEUED 行——
            # 若不撤销会永久虚增 queue_depth、误导 backpressure（记错账）。撤销自己那行。
            if scheduler is not None and scheduler_enqueued:
                try:
                    await scheduler.cancel(request_id)
                except Exception:
                    logger.warning("scheduler cancel on cache-hit failed", exc_info=True)

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
            admission_controller is not None
            and settings.admission_effective_enabled
            and decision is not None
            and decision.status == ADMISSION_QUEUED
        ):
            yield _sse({
                "type": "admission",
                "status": ADMISSION_QUEUED,
                "position": decision.queue_position,
            })
            decision = await admission_controller.wait_for_admit(request_id)
        if decision is not None and decision.status == ADMISSION_REJECTED:
            yield _sse({
                "type": "admission",
                "status": ADMISSION_REJECTED,
                "reason": decision.reason,
            })
            # 统一清理：_states[rid] 拗留 ADMISSION_REJECTED 且 DB 行仍是 ADMISSION_QUEUED →
            # count(ADMISSION_ADMITTED+ADMISSION_QUEUED) 永久含该记录，容量泄漏，直到进程重启
            # recover_on_startup 才清。mark_completed 会 pop 内存状态并把 DB 行
            # 标 completed，释放容量。走 lease.release() 统一出口，避免与外层重复清理。
            await lease.release()
            return
        if decision is not None and decision.status == ADMISSION_ADMITTED:
            yield _sse({
                "type": "admission",
                "status": ADMISSION_ADMITTED,
                "position": decision.queue_position,
            })
        # Phase 2: coordination queue 前置事件
        if coord_decision is not None and coord_decision.decision_type == "queue":
            yield _sse({"type": "coordination", "decision": "queue"})
            await coordinator.wait_for_turn(thread_id, request_id)

        # Phase 2: OTel request span
        span = None
        _span_cm = None
        _parent_ctx_cm = None
        if otel_tracer is not None:
            from agent_core.tracing_propagation import extract_traceparent, use_context

            _parent_ctx_cm = use_context(extract_traceparent(request.headers))
            _parent_ctx_cm.__enter__()
            _span_cm = otel_tracer.start_as_current_span("query")
            span = _span_cm.__enter__()
            span.set_attribute("thread_id", thread_id)
            span.set_attribute("priority", priority)
            for k, v in redact_question(req.query).items():
                span.set_attribute(k, v)

        try:
            final_answer = ""
            round_snapshot: dict | None = None
            _stream_failed = False
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
                # WS-2：从 thread 持久化读上一轮结构化快照，注入 PlannerContext；
                # 本轮 status 事件携带的 snapshot 随 append_thread 落 checkpoint。
                # Context Governance：在构建 PlannerContext 前，用 Governor
                # 召回 + 治理 Memory（Authorize → Validate → QualityScore），
                # 把治理后的记忆注入 PlannerContext.governed_memories。
                governor = getattr(request.app.state, "context_governor", None)
                governed_memories: list[str] = []
                last_snapshot = await _thread_persist.read_thread_snapshot(checkpointer, thread_id)
                if governor is not None:
                    try:
                        governed_memories, _gov_report = await governor.govern_memories(
                            query=req.query,
                            state=last_snapshot,
                            tenant_id=req.workspace_id,
                            user_id=req.user_id,
                        )
                    except Exception:
                        logger.warning("context governance failed, degrading", exc_info=True)
                ctx = PlannerContext(
                    question=req.query,
                    workspace_id=req.workspace_id,
                    user_id=req.user_id,
                    messages=await _thread_persist.read_thread_messages(checkpointer, thread_id),
                    llm=planner_runtime.llm,
                    last_snapshot=last_snapshot,
                    governed_memories=governed_memories,
                )
                plan = await planner.plan(ctx)
                # P0-1（方案 B）：Scheduler 认领已在进入流式前由 try_start 完成（见 handler 末尾），
                # 认领即置 RUNNING；不再调 dispatch_next()（旧写法无参会错标队首他人任务）。
                # V3 Phase 2: ExecutionStatus → RUNNING
                if status_store is not None:
                    from agent_runtime.execution_status import ExecutionStatus, ExecutionStatusRecord

                    try:
                        await status_store.save(ExecutionStatusRecord(
                            execution_id=request_id,
                            status=ExecutionStatus.RUNNING,
                        ))
                    except Exception:
                        logger.warning("status save RUNNING failed", exc_info=True)
                async for event in planner.execute(plan, planner_runtime):
                    sse = _stream_event(event)
                    if sse:
                        yield _sse(sse)
                    if event.type == "answer":
                        final_answer = event.payload.get("text", "")
                    elif event.type == "status" and event.payload.get("snapshot"):
                        round_snapshot = event.payload["snapshot"]
                    elif event.type == "suspended" and status_store is not None:
                        # V3-3: 执行挂起 → ExecutionStatus → WAITING_EXTERNAL
                        from agent_runtime.execution_status import ExecutionStatus, ExecutionStatusRecord

                        try:
                            await status_store.save(ExecutionStatusRecord(
                                execution_id=request_id,
                                status=ExecutionStatus.WAITING_EXTERNAL,
                            ))
                        except Exception:
                            logger.warning("status save WAITING_EXTERNAL failed", exc_info=True)
            if final_answer and q_embedding is not None:
                semantic_cache.cache_store(pool, req.query, final_answer, q_embedding, tenant_id=req.tenant_id or "")
            # Phase 3: 对话历史写回——Planner 协议中立（不持线程语义），由 app 层承担。
            # 与 graph 路径的 checkpoint 持久化行为等价，/history 与 revert 不回退。
            if final_answer and checkpointer is not None:
                await _thread_persist.append_thread(
                    checkpointer,
                    thread_id,
                    req.query,
                    final_answer,
                    snapshot=round_snapshot,
                )
            yield _sse({"type": "done", "thread_id": thread_id, "answer": final_answer})
        except Exception as exc:
            logger.exception("query stream failed: thread_id=%s", thread_id)
            _stream_failed = True
            yield _sse({"type": "error", "error": str(exc)})
            yield _sse({"type": "done", "thread_id": thread_id, "answer": ""})
        finally:
            if _span_cm is not None:
                _span_cm.__exit__(None, None, None)
            if _parent_ctx_cm is not None:
                _parent_ctx_cm.__exit__(None, None, None)
            # V3 Phase 2: Scheduler complete + ExecutionStatus → SUCCEEDED/FAILED
            # P0-1（方案 B）：complete 现带终态 status（COMPLETED/FAILED），槽位真实释放。
            if scheduler is not None and scheduler_enqueued:
                from agent_runtime.execution_scheduler import QueueStatus

                try:
                    await scheduler.complete(
                        request_id,
                        QueueStatus.FAILED if _stream_failed else QueueStatus.COMPLETED,
                    )
                except Exception:
                    logger.warning("scheduler complete failed", exc_info=True)
            if status_store is not None:
                from agent_runtime.execution_status import ExecutionStatus, ExecutionStatusRecord

                try:
                    await status_store.save(ExecutionStatusRecord(
                        execution_id=request_id,
                        status=ExecutionStatus.FAILED if _stream_failed else ExecutionStatus.SUCCEEDED,
                    ))
                except Exception:
                    logger.warning("status save terminal failed", exc_info=True)
            # V3 Phase 4: Cost Governance record（opt-in）
            if cost_governance is not None:
                from agent_runtime.cost_governance import BudgetDimension

                _tenant = req.tenant_id or "default"
                try:
                    await cost_governance.record(_tenant, BudgetDimension.REQUESTS, 1)
                    traj = getattr(planner_runtime, "last_trajectory", None)
                    if traj is not None:
                        if traj.total_tokens > 0:
                            await cost_governance.record(_tenant, BudgetDimension.TOKENS, traj.total_tokens)
                        if traj.total_cost > 0:
                            await cost_governance.record(_tenant, BudgetDimension.COST, traj.total_cost)
                except Exception:
                    logger.warning("cost governance record failed", exc_info=True)
            # Phase 2: 统一生命周期清理（幂等，覆盖 graph 异常 / 客户端断开 /
            # 正常完成）。reject 与 cache-hit 路径已在 _stream 外提前调用过，
            # 此处再调用安全无副作用（AsyncLease 幂等）。
            await lease.release()

    # V3 P0-1（方案 B）：真执行门控——认领本请求专属槽位（原子 QUEUED→RUNNING）。
    # 放在返回流之前：此时 admission/coordinator 的 reject 与 cache-hit 早退均已发生，
    # 认领成功唯一的出口是进入 _stream()，其 finally 必落终态释放，无槽位泄漏。
    if scheduler is not None and scheduler_enqueued:
        if await scheduler.try_start(request_id) is None:
            # 超并发：撤销刚入队的 QUEUED 行并拒绝（不占用槽位）。
            try:
                await scheduler.cancel(request_id)
            except Exception:
                logger.warning("scheduler cancel on gating reject failed", exc_info=True)
            raise HTTPException(
                status_code=503,
                detail="SCHEDULER_SLOTS_EXHAUSTED",
                headers={"Retry-After": "5"},
            )

    return StreamingResponse(_stream(), media_type="text/event-stream")


def _sse(payload: dict) -> str:
    """打包 SSE 帧：将 payload.type 提升为 event name，与 knowledge-service 对齐。"""
    event_name = payload.get("type", "")
    return sse_pack(event_name, payload)


def _node_event(node: str, payload: dict) -> dict | None:
    if node == "route":
        return {
            "type": "route",
            "capability": payload.get("route"),
            "reason": payload.get("route_reason"),
        }
    if node in ("search", "rag", "sql", "mcp", "code_execution"):
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
