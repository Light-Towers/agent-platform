"""Supervisor 图：route -> (search|rag|sql|direct) -> synthesize，证据不足可重试一次。

单进程多节点隔离（而非微服务）：子项目拆 HTTP 适配层已证明会引入
SSE 聚合、会话键、探活自递归等一串问题；这里用 LangGraph 节点边界隔离，
保留未来按节点拆服务的能力。
"""

import logging

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from app.agent.compact import compact_messages, should_compact
from app.agent.router import decide_route
from app.agent.state import AgentState
from app.config import get_settings
from app.infra.db import get_pool
from app.infra.mcp_client import MCPClientManager
from app.memory.longterm import recall, remember
from app.subagents.mcp import mcp_query
from app.subagents.rag import rag_query
from app.subagents.search import search_web
from app.subagents.sql_agent import sql_query

logger = logging.getLogger(__name__)

_SYNTHESIZE_PROMPT = (
    "你是严谨的助手。只根据下面的证据回答问题；证据不足时明确说明，不要编造。\n"
    "回答用中文，简明扼要，必要时列出来源。"
)


def build_graph(llm, checkpointer=None, mcp_manager: MCPClientManager | None = None):
    """构建并编译 Supervisor 图；llm 可为 None（无 LLM 模式）。"""

    async def route_node(state: AgentState) -> dict:
        question = state.question

        # 上下文压缩：多轮会话 token 超阈值时摘要旧消息
        settings = get_settings()
        messages = state.messages
        if settings.compaction_enabled and llm is not None:
            threshold = int(settings.model_context_window * settings.compaction_threshold_ratio)
            if should_compact(messages, threshold):
                compacted, err = await compact_messages(messages, llm)
                if err is None:
                    return {
                        "route": "direct",
                        "sub_query": question,
                        "route_reason": "上下文已压缩，重新路由",
                        "memory_notes": [],
                        "messages": compacted,
                        "iterations": state.iterations,
                    }

        decision = await decide_route(llm, question)
        memory_notes: list[str] = []
        if settings.memory_enabled:
            memory_notes = await recall(get_pool(), state.user_id, question)
        return {
            "route": decision.capability,
            "sub_query": decision.sub_query,
            "route_reason": decision.reason,
            "memory_notes": memory_notes,
        }

    async def search_node(state: AgentState) -> dict:
        return {"evidence": await search_web(state.sub_query)}

    async def rag_node(state: AgentState) -> dict:
        return {"evidence": await rag_query(state.sub_query)}

    async def sql_node(state: AgentState) -> dict:
        return {"evidence": await sql_query(state.sub_query, llm=llm)}

    async def direct_node(state: AgentState) -> dict:
        return {"evidence": []}

    async def mcp_node(state: AgentState) -> dict:
        return await mcp_query(state, mcp_manager)

    async def synthesize_node(state: AgentState) -> dict:
        question = state.question
        evidence = state.evidence
        memory_notes = state.memory_notes
        iterations = state.iterations

        # 反思：证据为空且未到重试上限，回到路由再来一次
        has_real_evidence = evidence and not any(
            e.startswith(("知识库未启用", "知识库中未检索到", "联网搜索未配置", "SQL_DSN 未配置"))
            for e in evidence
        )
        if not has_real_evidence and state.route != "direct" and iterations < get_settings().max_iterations:
            return {"iterations": iterations + 1, "evidence": []}

        answer = await _compose(question, evidence, memory_notes)
        if get_settings().memory_enabled:
            remember(get_pool(), state.user_id, f"Q: {question}\nA: {answer}")
        return {
            "answer": answer,
            "iterations": iterations,
            "messages": [AIMessage(content=answer)],
        }

    async def _compose(question: str, evidence: list[str], memory_notes: list[str]) -> str:
        if llm is None:
            # 无 LLM 模式：模板拼装，保证链路可验收
            parts = [f"（无 LLM 模式）针对问题「{question}」收集到的证据："]
            if evidence:
                parts.extend(f"- {e}" for e in evidence)
            else:
                parts.append("- 无")
            if memory_notes:
                parts.append("相关历史记忆：" + "；".join(memory_notes))
            return "\n".join(parts)
        blocks = [f"## 证据\n{i}. {e}" for i, e in enumerate(evidence, start=1)] or ["## 证据\n（无）"]
        if memory_notes:
            blocks.append("## 历史记忆\n" + "\n".join(f"- {m}" for m in memory_notes))
        blocks.append(f"## 问题\n{question}")
        raw = await llm.ainvoke(
            [
                {"role": "system", "content": _SYNTHESIZE_PROMPT},
                {"role": "user", "content": "\n\n".join(blocks)},
            ]
        )
        return raw.content if hasattr(raw, "content") else str(raw)

    def pick_capability(state: AgentState) -> str:
        return state.route

    def next_after_synthesize(state: AgentState) -> str:
        # synthesize 重试分支返回空 answer 且 iterations 已增加
        if not state.answer and state.iterations > 0:
            return "route"
        return END

    builder = StateGraph(AgentState)
    builder.add_node("route", route_node)
    builder.add_node("search", search_node)
    builder.add_node("rag", rag_node)
    builder.add_node("sql", sql_node)
    builder.add_node("direct", direct_node)
    builder.add_node("mcp", mcp_node)
    builder.add_node("synthesize", synthesize_node)

    builder.add_edge(START, "route")
    builder.add_conditional_edges(
        "route",
        pick_capability,
        {"search": "search", "rag": "rag", "sql": "sql", "direct": "direct", "mcp": "mcp"},
    )
    builder.add_edge("search", "synthesize")
    builder.add_edge("rag", "synthesize")
    builder.add_edge("sql", "synthesize")
    builder.add_edge("direct", "synthesize")
    builder.add_edge("mcp", "synthesize")
    builder.add_conditional_edges("synthesize", next_after_synthesize, {"route": "route", END: END})

    return builder.compile(checkpointer=checkpointer)
