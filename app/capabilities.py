"""app 侧 Capability Registry 装配（Plan-F Phase 1 + Phase 1.5 + Phase 3）。

注册 search/rag/sql/mcp 四个进程内能力（原子 Skill），以及 graph 包装的
``general_qa`` Workflow Skill（静态 DAG 执行器，Phase 3：graph.py 不删除、
降级为一个可注册能力的实现）。Planner / Agent 经注册表统一调用任意能力。

Skill 契约（Phase 1.5）：每个能力带 input/output JSON Schema，Planner / Agent
经 ``to_tool_schema()`` 生成工具描述——能力实现细节（函数 / 静态 DAG / 远程）
对调用方保持黑盒。

注册表为模块级惰性单例（幂等），进程生命周期内复用。
"""

from __future__ import annotations

from functools import partial
from typing import Any

from agent_runtime.mcp_client import MCPClientManager
from agent_runtime.skills.dag import as_dag_skill
from agent_runtime.skills.function import as_function_skill
from agent_runtime.skills.registry import SkillRegistry

from app.agent.state import AgentState
from app.subagents.mcp import mcp_query
from app.subagents.rag import rag_query
from app.subagents.search import search_web
from app.subagents.sql_agent import sql_query

_registry: SkillRegistry | None = None

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
        "thread_id": {"type": "string", "description": "会话线程 ID（对话历史持久化）"},
    },
    "required": ["question"],
}

_GENERAL_QA_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
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
            "iterations": 0,
        },
        config={"configurable": {"thread_id": kwargs.get("thread_id", "default")}},
        stream_mode="updates",
    ):
        for _node, payload in update.items():
            if isinstance(payload, dict) and payload.get("answer"):
                answer = payload["answer"]
    return answer


def build_registry(graph: Any | None = None) -> SkillRegistry:
    """构建 app 能力注册表（幂等；重复调用返回新实例，供测试隔离）。

    graph（可选）：LangGraph 静态图实例。注入时额外注册 ``general_qa`` Workflow Skill
    （Phase 3：graph.py 包装而非删除，供 Planner / Agent 组合调用）。
    """
    registry = SkillRegistry()
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
    return registry


def get_registry(graph: Any | None = None) -> SkillRegistry:
    """进程级单例注册表。

    graph 仅首次构建时生效（lifespan 装配 general_qa 时注入）；后续调用幂等返回同一实例。
    """
    global _registry
    if _registry is None:
        _registry = build_registry(graph=graph)
    return _registry
