"""app 侧 Capability Registry 装配（Plan-F Phase 1 + Phase 1.5 + Phase 3）。

注册 search/rag/sql/mcp 四个进程内能力（原子 Skill），以及 graph 包装的
``general_qa`` Workflow Skill（静态 DAG 执行器，Phase 3：graph.py 不删除、
降级为一个可注册能力的实现）。Planner / Agent 经注册表统一调用任意能力。

Skill 契约（Phase 1.5）：每个能力带 input/output JSON Schema，Planner / Agent
经 ``to_tool_schema()`` 生成工具描述——能力实现细节（函数 / 静态 DAG / 远程）
对调用方保持黑盒。

Runtime 边界（架构审核 P1）：熔断经 ``CircuitBreakerMiddleware`` 挂在注册表
洋葱链上（仅包裹 search，隔离故障域），search 实现不再内嵌 breaker——
边界从实现内收敛到统一执行入口。

注册表为模块级惰性单例（幂等），进程生命周期内复用。
"""

from __future__ import annotations

import logging
from functools import partial
from typing import Any

from agent_runtime.circuit_breaker import CircuitBreaker
from agent_runtime.mcp_client import MCPClientManager
from agent_runtime.skills.dag import as_dag_skill
from agent_runtime.skills.function import as_function_skill
from agent_runtime.skills.middleware import AuditMiddleware, CircuitBreakerMiddleware, RetryMiddleware
from agent_runtime.skills.registry import SkillRegistry

from agent_server.agent.state import AgentState
from agent_server.config import get_settings
from agent_server.subagents.mcp import mcp_query
from agent_server.subagents.rag import rag_query
from agent_server.subagents.search import search_web
from agent_server.subagents.sql_agent import sql_query

_registry: SkillRegistry | None = None
_breaker: CircuitBreaker | None = None

# Skill 契约（Phase 1.5）：JSON Schema——供 Agent 工具描述生成与入参校验
_QUERY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "搜索/检索的查询文本"},
    },
    "required": ["query"],
}

_RAG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "检索的查询文本"},
        "workspace_id": {"type": "string", "description": "知识库空间 ID，缺省 default"},
    },
    "required": ["query"],
}

_GENERAL_QA_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "question": {"type": "string", "description": "用户问题"},
        "workspace_id": {"type": "string", "description": "知识库空间 ID，缺省 default"},
        "user_id": {"type": "string", "description": "用户 ID，缺省 default"},
        "tenant_id": {"type": "string", "description": "租户 ID，缺省 default（记忆读写按租户隔离）"},
        "thread_id": {"type": "string", "description": "会话线程 ID（对话历史持久化）"},
    },
    "required": ["question"],
}

_GENERAL_QA_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "string",
    "description": "最终回答文本",
}


async def _mcp_execute(state: AgentState, mcp_manager: MCPClientManager | None) -> dict[str, Any]:
    """mcp 能力适配：签名依赖 state + manager（与 search/rag/sql 的 query 形态不同）。"""
    return await mcp_query(state, mcp_manager)


async def _run_general_qa(graph: Any, **kwargs: Any) -> str:
    """general_qa Workflow Skill 执行器：跑静态 DAG（graph.astream 全链路），归约为最终 answer。

    graph 保留 checkpoint（thread_id 恢复/持久化对话历史）语义；对调用方是黑盒 Skill。
    """
    question = kwargs["question"]
    answer = ""
    async for update in graph.astream(
        {
            "messages": [("user", question)],
            "question": question,
            "user_id": kwargs.get("user_id", "default"),
            "workspace_id": kwargs.get("workspace_id", "default"),
            # 租户身份随 state 注入：缺失会在 default 桶读写记忆，造成跨租户可见
            "tenant_id": kwargs.get("tenant_id", "default"),
            "iterations": 0,
        },
        config={"configurable": {"thread_id": kwargs.get("thread_id", "default")}},
        stream_mode="updates",
    ):
        for _node, payload in update.items():
            if isinstance(payload, dict) and payload.get("answer"):
                answer = payload["answer"]
    return answer


def _get_breaker() -> CircuitBreaker:
    """search 熔断器单例：参数取 settings（与 main.py MCP manager 同源语义）。"""
    global _breaker
    if _breaker is None:
        settings = get_settings()
        _breaker = CircuitBreaker(
            failure_threshold=settings.breaker_failure_threshold,
            recovery_seconds=settings.breaker_recovery_seconds,
        )
    return _breaker


_audit_logger = logging.getLogger("skill.audit")


async def _audit_sink(name: str, kwargs: dict, result: Any, error: str | None, latency_s: float) -> None:
    """审计 sink：记录每次 Skill 调用的审计事件（合规留痕 / 攻击溯源）。"""
    _audit_logger.info(
        "skill_call name=%s latency=%.3fs error=%s",
        name,
        latency_s,
        error or "none",
    )


# C-3: 进程级共享 httpx.AsyncClient（连接池复用，避免每次 skill 调用新建 client）
_http_client: Any = None


def _get_http_client() -> Any:
    """惰性创建进程级 httpx.AsyncClient（连接池复用）。"""
    global _http_client
    if _http_client is None:
        import httpx

        _http_client = httpx.AsyncClient(timeout=30)
    return _http_client


def build_registry(graph: Any | None = None) -> SkillRegistry:
    """构建 app 能力注册表（幂等；重复调用返回新实例，供测试隔离）。

    graph（可选）：LangGraph 静态图实例。注入时额外注册 ``general_qa`` Workflow Skill
    （Phase 3：graph.py 包装而非删除，供 Planner / Agent 组合调用）。

    Runtime 边界（架构审核 P1）：熔断经中间件链收敛——``CircuitBreakerMiddleware``
    仅包裹 search（隔离故障域），search 实现不再内嵌 breaker。
    """
    middlewares = [
        CircuitBreakerMiddleware(_get_breaker(), skill_names=("search",)),
        RetryMiddleware(max_retries=2, backoff_s=0.5),
        AuditMiddleware(_audit_sink, redact=True),
    ]
    settings = get_settings()
    if settings.tool_result_compression_enabled:
        from agent_runtime.skills.middleware import ToolResultCompressionMiddleware

        middlewares.append(
            ToolResultCompressionMiddleware(
                max_tokens=settings.tool_result_max_tokens,
                store_dir=settings.tool_result_store_dir or None,
            )
        )
    registry = SkillRegistry(middlewares=middlewares)
    registry.register(
        as_function_skill(
            "search",
            "联网搜索（Tavily）：返回证据字符串列表",
            search_web,
            input_schema=_QUERY_SCHEMA,
        )
    )
    registry.register(
        as_function_skill(
            "rag",
            "知识库混合检索：按 workspace 过滤，返回证据字符串列表",
            rag_query,
            input_schema=_RAG_SCHEMA,
        )
    )
    registry.register(
        as_function_skill(
            "sql",
            "SQL 查询：text-to-SQL 管线，返回证据字符串列表",
            sql_query,
            input_schema=_QUERY_SCHEMA,
        )
    )
    registry.register(
        as_function_skill(
            "mcp",
            "MCP 工具调用：调用外部工具并归约为 evidence（依赖 state + manager）",
            _mcp_execute,
        )
    )
    if graph is not None:
        registry.register(
            as_dag_skill(
                "general_qa",
                "通用问答（Workflow Skill）：端到端 QA 流水线——输入护栏 → 路由 → "
                "检索/搜索/SQL/MCP → 答案合成，返回最终回答字符串",
                partial(_run_general_qa, graph),
                input_schema=_GENERAL_QA_INPUT_SCHEMA,
                output_schema=_GENERAL_QA_OUTPUT_SCHEMA,
                timeout_ms=120_000,
            )
        )
    _register_remote_skills(registry)
    return registry


def _register_remote_skills(registry: SkillRegistry) -> None:
    """P1：注册重服务为 RemoteExecutor skill（HTTP 调用）。

    URL 未配置时跳过（不崩溃、不警告——开发环境常见只起 agent_server）。
    重依赖（torch/Milvus/Neo4j/pgvector）隔离在远端进程，编排进程不传染。
    """
    import os

    from agent_runtime.skills.remote import as_remote_skill

    knowledge_url = os.getenv("KNOWLEDGE_SERVICE_URL", "")
    if knowledge_url:
        knowledge_key = os.getenv("KNOWLEDGE_SERVICE_KEY", "")

        async def _knowledge_query(**kwargs: Any) -> Any:
            headers = {"Authorization": f"Bearer {knowledge_key}"} if knowledge_key else {}
            client = _get_http_client()
            resp = await client.post(f"{knowledge_url}/query", json=kwargs, headers=headers)
            resp.raise_for_status()
            return resp.json()

        registry.register(
            as_remote_skill(
                "knowledge_query",
                "知识库问答：RAG 检索 + LLM 生成，返回答案文本",
                _knowledge_query,
                timeout_ms=30_000,
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "查询文本"},
                        "session_id": {"type": "string", "description": "会话 ID"},
                    },
                    "required": ["query"],
                },
            )
        )

        async def _knowledge_retrieve(**kwargs: Any) -> Any:
            headers = {"Authorization": f"Bearer {knowledge_key}"} if knowledge_key else {}
            client = _get_http_client()
            resp = await client.post(f"{knowledge_url}/api/v1/retrieve", json=kwargs, headers=headers)
            resp.raise_for_status()
            return resp.json()

        registry.register(
            as_remote_skill(
                "knowledge_retrieve",
                "知识库纯检索：embedding→RRF→rerank，返回文档列表（无 LLM 生成）",
                _knowledge_retrieve,
                timeout_ms=30_000,
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "检索文本"},
                        "tenant_id": {"type": "string", "description": "租户 ID"},
                        "scope_type": {"type": "string", "description": "PUBLIC 或 PRIVATE"},
                    },
                    "required": ["query", "tenant_id"],
                },
            )
        )

    nl2sql_url = os.getenv("NL2SQL_SERVICE_URL", "")
    if nl2sql_url:

        async def _nl2sql_query(**kwargs: Any) -> Any:
            client = _get_http_client()
            resp = await client.post(f"{nl2sql_url}/api/query", json=kwargs)
            resp.raise_for_status()
            return resp.json()

        registry.register(
            as_remote_skill(
                "nl2sql_query",
                "Text-to-SQL：自然语言→SQL→执行→结果，返回 SQL + 查询结果",
                _nl2sql_query,
                timeout_ms=30_000,
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "自然语言查询"},
                    },
                    "required": ["query"],
                },
            )
        )

    kefu_url = os.getenv("KEFU_SERVICE_URL", "")
    if kefu_url:

        async def _kefu_query(**kwargs: Any) -> Any:
            client = _get_http_client()
            resp = await client.post(f"{kefu_url}/invoke", json=kwargs)
            resp.raise_for_status()
            return resp.json()

        registry.register(
            as_remote_skill(
                "kefu_query",
                "客服问答：意图路由 + Flow + GraphRAG，返回客服回复",
                _kefu_query,
                timeout_ms=30_000,
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "用户消息"},
                        "session_id": {"type": "string", "description": "会话 ID"},
                    },
                    "required": ["query"],
                },
            )
        )

    exhibition_url = os.getenv("EXHIBITION_SERVICE_URL", "")
    if exhibition_url:

        async def _exhibition_query(**kwargs: Any) -> Any:
            client = _get_http_client()
            resp = await client.post(f"{exhibition_url}/api/query", json=kwargs)
            resp.raise_for_status()
            return resp.json()

        registry.register(
            as_remote_skill(
                "exhibition_query",
                "会展查询：Supervisor 图路由 → warehouse REST，返回 answer + readiness + citations",
                _exhibition_query,
                timeout_ms=30_000,
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "查询文本"},
                        "params": {
                            "type": "object",
                            "description": "附加参数（tenant_id 等）",
                        },
                    },
                    "required": ["query"],
                },
            )
        )


def get_registry(graph: Any | None = None) -> SkillRegistry:
    """进程级单例注册表。

    graph 仅首次构建时生效（lifespan 装配 general_qa 时注入）；后续调用幂等返回同一实例。
    """
    global _registry
    if _registry is None:
        _registry = build_registry(graph=graph)
    return _registry
