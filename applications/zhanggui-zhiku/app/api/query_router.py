# -*- coding: utf-8 -*-
"""
查询路由（从原 query_service.py 抽取为 FastAPI 子路由）。

职责：
- /chat.html：返回对话前端页面；
- /health：健康检查；
- /query：接收用户提问，触发 LangGraph 查询流程（支持流式 / 同步两种模式）；
- /stream/{session_id}：SSE 实时推送检索/生成进度与答案；
- /history/{session_id}：GET 查询会话历史 / DELETE 清空会话历史。

跨域（CORS）统一在 app.main.create_app() 中配置，本路由不再单独处理。
"""

import uuid
from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.utils.task_utils import *
from app.utils.sse_utils import create_sse_queue, SSEEvent, sse_generator
from app.clients.mongo_history_utils import *
from app.query_process.agent.main_graph import query_app
from app.conf.retrieval_config import retrieval_cfg
from app.core.config import PROJECT_ROOT, settings
from app.core.logger import logger
from app.core.tracing import generate_request_id, set_request_context, start_span, user_query_hash

# 子路由实例：由 create_app() 挂载到根路径
router = APIRouter()


# 返回chat.html页面
@router.get("/chat.html")  # 对外访问地址
async def chat():
    # 统一基于 PROJECT_ROOT 定位页面，避免依赖 __file__ 相对路径（更稳健）
    chat_html_path = PROJECT_ROOT / "app/query_process/page/chat.html"
    # 如果不存在，抛出404异常（M5：错误信息不泄露内部路径，脱敏文案）
    if not chat_html_path.exists():
        raise HTTPException(status_code=404, detail="对话页面不存在")
    return FileResponse(chat_html_path)


# 定义接口接收的数据结构（M5：入站长度护栏，方案 §9）
class HistoryItem(BaseModel):
    """历史对话项（单条长度上限，防单条超长注入 prompt）"""

    role: str = Field(default="", max_length=32, description="角色：user/assistant")
    text: str = Field(default="", max_length=4096, description="对话内容（上限 4096 字符）")


class QueryRequest(BaseModel):
    """查询请求数据结构（M5：入站长度护栏，方案 §9）"""

    query: str = Field(..., min_length=1, max_length=512, description="查询内容（上限 512 字符）")
    session_id: str = Field(None, max_length=128, description="会话ID")
    is_stream: bool = Field(False, description="是否流式返回")
    history: List[HistoryItem] = Field(default_factory=list, description="可选历史对话（超限截断保留最近 N 轮）")


class RetrieveRequest(BaseModel):
    """纯检索请求（M6，§10.6 /retrieve 压测档；与 QueryRequest 同长度护栏）"""

    query: str = Field(..., min_length=1, max_length=512, description="查询内容（上限 512 字符）")
    item_name: str = Field("", max_length=128, description="商品名（Milvus item_name 过滤依据）")


# 证明服务器启动即可
@router.get("/health")
async def health():
    """
    检查服务是否正常
    """
    return {"ok": True}


# M6（方案 §2.2）：存活 / 就绪双探针（compose healthcheck 使用；旧 /health 保留兼容）。
# 注意：/health/live 与 /health/ready 已在 M5 安全护栏中按 /health* 前缀豁免鉴权/限流，
# 启用 ZHANGUI_API_KEY 后容器探针仍可通过（见 security_guard_utils.is_health_path）。
@router.get("/health/live")
async def health_live():
    """存活探针：进程活着即返回 200（不依赖外部组件）。"""
    return {"ok": True}


@router.get("/health/ready")
async def health_ready():
    """
    就绪探针：检索主依赖（Milvus）连通才返回 200，否则 503（便于 LB / compose 摘除不健康实例）。

    说明：以 Milvus 为就绪判据（检索必经依赖）；Neo4j 驱动 verify_connectivity 无轻量
    超时，暂不纳入避免探针挂起，后续可按需扩展。探针内部不抛异常，只标记不健康。
    """
    checks: dict = {"milvus": False}
    ready = False
    try:
        from app.clients.milvus_utils import milvus_ready

        checks["milvus"] = milvus_ready()
        ready = checks["milvus"]
    except Exception as e:  # noqa: BLE001 —— 探针不抛异常，只标记不健康
        logger.warning("health/ready milvus check failed: %s", e)
    if not ready:
        return JSONResponse(status_code=503, content={"ok": False, "checks": checks})
    return {"ok": True, "checks": checks}


# 定义查询接口
def run_query_graph(
    session_id: str,
    user_query: str,
    is_stream: bool = True,
    request_id: Optional[str] = None,
):
    logger.info(f"开始流程图处理...{session_id} {user_query} {is_stream}")

    # M4：请求级追踪上下文（request.total 根 span + 统一 request_id / user_query_hash 属性，
    # 方案 §8.2 表；response 头 X-Trace-Id 与后台任务共用同一 request_id）。
    trace_request_id = request_id or generate_request_id()
    trace_query_hash = user_query_hash(user_query)
    set_request_context(request_id=trace_request_id, user_query_hash=trace_query_hash)

    default_state = {"original_query": user_query, "session_id": session_id, "is_stream": is_stream}
    with start_span(
        "request.total",
        attrs={"request_id": trace_request_id, "user_query_hash": trace_query_hash, "session_id": session_id},
    ) as span:
        try:
            # 后期运行
            query_app.invoke(default_state)
            # 整体任务就更新完了！ 接下来就是数据的更新了！
            update_task_status(session_id, TASK_STATUS_COMPLETED, is_stream)
        except Exception as e:
            logger.error(f"流程执行异常: {e}")
            try:
                span.record_exception(e)
            except Exception as e2:
                logger.warning("记录异常到 span 失败: %s", e2)
            update_task_status(session_id, TASK_STATUS_FAILED, is_stream)
            if is_stream:
                push_to_session(session_id, SSEEvent.ERROR, {"error": str(e)})


@router.post("/query")
async def query(background_tasks: BackgroundTasks, request: Request, payload: QueryRequest):
    """
    1 解析参数
    2 更新任务状态
    3 调用处理流程图
    4 返回结果
    :param background_tasks:
    :param request: Starlette Request（用于取中间件注入的 request_id）
    :param payload: 业务请求体（QueryRequest 为 Pydantic 模型，无 .state 属性）
    :return:
    """
    user_query = payload.query
    session_id = payload.session_id if payload.session_id else str(uuid.uuid4())

    # M4/M5：请求级 trace id（优先复用 SecurityGuardsMiddleware 注入的 request_id，
    # 保证 401/429/400 与正常响应、后台任务共用同一 trace；无 middleware 时兜底生成）
    # 注意：request_id 由中间件写在 Starlette Request.state 上，故此处必须取 request（Request 类型），
    # 而非 payload（Pydantic 模型，无 .state）；此前误用 payload.state 导致所有 /query 直接 500。
    trace_request_id = getattr(request.state, "request_id", None) or generate_request_id()

    # M5：历史轮数护栏（超限截断保留最近 N 轮，防 prompt 无限膨胀）。
    # 说明：当前检索管线历史来自 MongoDB（node_item_name_confirm 服务端 limit=10 已兜底），
    # 入站 history 字段为兼容/预留（方案 §9 ChatRequest 设计），超限截断后透传。
    history = payload.history
    if len(history) > settings.zhanggui_max_history_rounds:
        logger.warning(
            "history 轮数超限（%d > %d），截断保留最近 %d 轮",
            len(history),
            settings.zhanggui_max_history_rounds,
            settings.zhanggui_max_history_rounds,
        )
        history = history[-settings.zhanggui_max_history_rounds :]

    # 处理是不是流式返回结果
    is_stream = payload.is_stream
    if is_stream:
        # 创建一个字典 存储对一个session_id : queue 结果队列
        create_sse_queue(session_id)
    # 更新任务状态
    # 当前会话id作为key! 整体装填处于运行中！
    update_task_status(session_id, TASK_STATUS_PROCESSING, is_stream)

    logger.info(f"开始处理流程... 是否流式: {is_stream} 其他参数:{user_query}, session_id:{session_id}")

    if is_stream:
        # 如果是流式，则返回一个流式响应，过程不断地推送
        # 运行执行图对象方法
        background_tasks.add_task(run_query_graph, session_id, user_query, is_stream, trace_request_id)
        # 返回结果
        logger.info("开始处理结果....")
        return JSONResponse(
            {"message": "结果正在处理中...", "session_id": session_id},
            headers={"X-Trace-Id": trace_request_id},
        )
    else:
        # 同步运行
        run_query_graph(session_id, user_query, is_stream, trace_request_id)
        answer = get_task_result(session_id, "answer", "")
        return JSONResponse(
            {"message": "处理完成！", "session_id": session_id, "answer": answer, "done_list": []},
            headers={"X-Trace-Id": trace_request_id},
        )


@router.post("/api/v1/retrieve")
async def retrieve(payload: RetrieveRequest):
    """
    纯检索链路（M6，§10.6 /retrieve 压测档）：embedding 召回 → 加权 RRF → BGE 重排，
    **不含 LLM 生成**（全部为自有组件，压测 QPS 目标 ≥ 100 / P95 < 3s，实测后回填
    benchmark/README.md 空模板，禁止预填）。

    链路与线上节点同一函数 / 同一参数（RRF k/max_results/weights 读 retrieval.yaml，
    与 node_rrf 一致）；与 eval/run_eval.retrieve_one 同口径（该处为硬编码快照版）。
    """
    # 懒导入：与线上检索链同一批节点函数（query_router 顶部已加载 main_graph，
    # 此处再引仅为了直接复用节点函数本身，避免经 graph 全链路含生成）
    from app.query_process.agent.nodes.node_search_embedding import node_search_embedding
    from app.query_process.agent.nodes.node_rrf import _as_entity_list, reciprocal_rank_fusion
    from app.query_process.agent.nodes.node_rerank import node_rerank

    session_id = f"retrieve_{uuid.uuid4().hex[:12]}"
    state = {
        "session_id": session_id,
        "original_query": payload.query,
        "rewritten_query": payload.query,
        "item_names": [payload.item_name] if payload.item_name else [],
        "is_stream": False,
    }

    # 1) 召回：embedding 路（与线上 node_search_embedding 同一函数；M6 fanout 超时隔离已作用于线上图）
    emb_result = node_search_embedding(state)
    embedding_weight = float(retrieval_cfg.rrf.weights.get("embedding", 1.0))
    sources = [(_as_entity_list(emb_result.get("embedding_chunks")), embedding_weight)]

    # 2) 融合：加权 RRF（与线上 node_rrf 同一配置源）
    rrf_cfg = retrieval_cfg.rrf
    fused = reciprocal_rank_fusion(sources, k=rrf_cfg.k, max_results=rrf_cfg.max_results)
    rrf_chunks = [doc for doc, _score in fused]

    # 3) 重排：BGE reranker + 动态 TopK（异常由节点降级为原序；与线上 node_rerank 同一函数）
    rerank_state = dict(state)
    rerank_state["rrf_chunks"] = rrf_chunks
    rerank_state["web_search_docs"] = []
    reranked = node_rerank(rerank_state).get("reranked_docs", [])

    return {"query": payload.query, "hits": len(reranked), "docs": reranked}


@router.get("/stream/{session_id}")
async def stream(session_id: str, request: Request):
    logger.info("调用流式/stream...")
    """
    sse 实时返回结果
    """
    return StreamingResponse(
        sse_generator(session_id, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.get("/history/{session_id}")
async def history(session_id: str, limit: int = Query(50, ge=1, le=200)):
    """
    查询当前会话历史记录（M5：limit 上限 200，防一次性拉取全量）
    """
    try:
        records = get_recent_messages(session_id, limit=limit)
        items = []
        for r in records:
            items.append(
                {
                    "_id": str(r.get("_id")) if r.get("_id") is not None else "",
                    "session_id": r.get("session_id", ""),
                    "role": r.get("role", ""),
                    "text": r.get("text", ""),
                    "rewritten_query": r.get("rewritten_query", ""),
                    "item_names": r.get("item_names", []),
                    "ts": r.get("ts"),
                }
            )
        return {"session_id": session_id, "items": items}
    except Exception:
        # M5：对外脱敏（详情仅入服务端日志，不泄露内部异常细节）
        logger.exception("history error for session %s", session_id)
        raise HTTPException(status_code=500, detail="获取会话历史失败")


@router.delete("/history/{session_id}")
async def clear_chat_history(session_id: str):
    count = clear_history(session_id)
    return {"message": "History cleared", "deleted_count": count}
