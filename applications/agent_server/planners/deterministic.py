"""DeterministicPlanner：确定性决策 + 编排执行（Plan-F Phase 2）。

从 ``app/agent/graph.py`` 提炼：决策逻辑（护栏/压缩/L1/LLM 路由）进 ``plan()``，
能力编排（记忆召回/能力调用/反思重试/合成/记忆沉淀）进 ``execute()``。
与 graph 节点**同源**复用模块级函数（router/compact/intent_bridge/memory/longterm），
避免双份逻辑漂移；Phase 3 retire ``app/graph.py`` 后此为唯一确定性实现。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from agent_core.guardrails.input_guard import guard_input
from agent_runtime.planner.protocol import Plan, Planner, PlannerContext, PlannerRuntime, StreamEvent

from agent_server.agent.compact import compact_messages, should_compact
from agent_server.agent.intent_bridge import l1_route_hint
from agent_server.agent.router import decide_route
from agent_server.agent.state import AgentState
from agent_server.config import get_settings
from agent_server.memory.longterm import extract_memory_facts, maybe_consolidate, recall, remember

logger = logging.getLogger(__name__)

_SYNTHESIZE_PROMPT = (
    "你是严谨的助手。只根据下面的证据回答问题；证据不足时明确说明，不要编造。\n"
    "回答用中文，简明扼要，必要时列出来源。"
)

_EMPTY_EVIDENCE_MARKERS = ("知识库未启用", "知识库中未检索到", "联网搜索未配置", "SQL_DSN 未配置")


def _message_content(msg: Any) -> str:
    """从 LangChain 消息 / dict / 裸串提取文本（与 compact._msg_content 同构）。"""
    if hasattr(msg, "content"):
        return str(msg.content)
    if isinstance(msg, dict):
        return str(msg.get("content", ""))
    return str(msg)


class DeterministicPlanner(Planner):
    """确定性 Planner：复刻 graph.py ``route -> (search|rag|sql|direct|mcp) -> synthesize`` 决策与编排。"""

    kind = "deterministic"

    async def plan(self, ctx: PlannerContext) -> Plan:
        settings = get_settings()
        question = ctx.question

        # 输入护栏：PII 脱敏 + prompt injection 检测（opt-in，与 graph.route_node 同源）
        if settings.guard_enabled:
            guard = guard_input(question)
            if guard["blocked"]:
                return Plan(
                    route="blocked",
                    sub_query="",
                    reason="被输入护栏拦截（injection）",
                    notes={"question": question, "workspace_id": ctx.workspace_id, "user_id": ctx.user_id},
                )
            question = guard["redacted_text"]

        # 上下文压缩：多轮会话 token 超阈值时摘要旧消息（与 graph.route_node 同源）
        if settings.compaction_enabled and ctx.llm is not None:
            threshold = int(settings.model_context_window * settings.compaction_threshold_ratio)
            model_name = getattr(ctx.llm, "model_name", None) or getattr(ctx.llm, "model", None)
            if should_compact(ctx.messages, threshold, model_name):
                compacted, err = await compact_messages(ctx.messages, ctx.llm, model_name)
                if err is None:
                    return Plan(
                        route="direct",
                        sub_query=question,
                        reason="上下文已压缩，重新路由",
                        notes={
                            "question": question,
                            "workspace_id": ctx.workspace_id,
                            "user_id": ctx.user_id,
                            "messages": compacted,
                        },
                    )

        # L1 轻量 short-circuit：高置信 chitchat 直答（与 graph.route_node 同源，eval 基线不受影响）
        l1_hint = l1_route_hint(question)
        if l1_hint is not None:
            return Plan(
                route=l1_hint,
                sub_query=question,
                reason="L1 chitchat short-circuit",
                notes={"question": question, "workspace_id": ctx.workspace_id, "user_id": ctx.user_id},
            )

        # LLM 主路由：失败自动回退确定性启发式（decide_route 内部处理）
        decision = await decide_route(ctx.llm, question)
        return Plan(
            route=decision.capability,
            sub_query=decision.sub_query,
            reason=decision.reason,
            notes={
                "question": question,
                "workspace_id": ctx.workspace_id,
                "user_id": ctx.user_id,
                "mcp_server": ctx.mcp_server,
                "mcp_tool": ctx.mcp_tool,
                "mcp_params": ctx.mcp_params,
            },
        )

    async def execute(
        self, plan: Plan, runtime: PlannerRuntime
    ) -> AsyncIterator[StreamEvent]:
        settings = get_settings()
        question = plan.notes.get("question") or plan.sub_query or ""
        workspace_id = plan.notes.get("workspace_id", "default")

        yield StreamEvent(type="route", payload={"capability": plan.route, "reason": plan.reason})
        if plan.route == "blocked":
            yield StreamEvent(type="answer", payload={"text": "抱歉，您的输入包含不安全的内容，请重新描述。"})
            return

        # 记忆召回（决策后执行期；pool 为 None 时跳过——memory 依赖 DB 池）
        memory_notes: list[str] = []
        if settings.memory_enabled and runtime.pool is not None:
            memory_notes = await recall(runtime.pool, workspace_id, question)
            if memory_notes:
                yield StreamEvent(type="memory", payload={"notes": memory_notes})

        # 能力调用 + 反思重试：证据为空且未到上限时回到 plan 重新决策（与 synthesize_node 同源）
        iterations = int(plan.notes.get("iterations") or 0)
        while True:
            evidence = await self._run_capability(plan, runtime, workspace_id, question)
            yield StreamEvent(
                type="evidence",
                payload={"node": plan.route, "count": len(evidence), "preview": evidence[0][:200] if evidence else ""},
            )
            has_real = evidence and not any(e.startswith(_EMPTY_EVIDENCE_MARKERS) for e in evidence)
            if not has_real and plan.route != "direct" and iterations < settings.max_iterations:
                iterations += 1
                plan = await self.plan(
                    PlannerContext(
                        question=question,
                        workspace_id=workspace_id,
                        user_id=plan.notes.get("user_id", "default"),
                        messages=[],
                        llm=runtime.llm,
                    )
                )
                yield StreamEvent(type="status", payload={"retry": True, "iterations": iterations, "route": plan.route})
                continue
            break

        # 合成 + 记忆沉淀（与 synthesize_node 同源）
        # compaction 路径：plan() 把摘要写入 notes["messages"]，这里消费它作为合成上下文
        context_messages = plan.notes.get("messages") or []
        answer = await self._compose(question, evidence, memory_notes, runtime.llm, context_messages)
        if settings.memory_enabled and runtime.pool is not None:
            facts = None
            if settings.memory_extraction_enabled and runtime.llm is not None:
                facts = await extract_memory_facts(runtime.llm, question, answer)
            await remember(runtime.pool, workspace_id, f"Q: {question}\nA: {answer}", facts=facts)
            await maybe_consolidate(runtime.pool, workspace_id)
        yield StreamEvent(type="answer", payload={"text": answer})

    async def _run_capability(
        self, plan: Plan, runtime: PlannerRuntime, workspace_id: str, question: str
    ) -> list[str]:
        """按 Plan.route 经 SkillRegistry 执行能力，结果归一化为 evidence 列表。"""
        if plan.route == "direct":
            return []
        if plan.route == "mcp":
            if runtime.mcp_manager is None:
                return ["MCP 未启用"]
            state = AgentState(
                question=question,
                sub_query=plan.sub_query or question,
                user_id=plan.notes.get("user_id", "default"),
                workspace_id=workspace_id,
                mcp_server=plan.notes.get("mcp_server", ""),
                mcp_tool=plan.notes.get("mcp_tool", ""),
                mcp_params=plan.notes.get("mcp_params", {}),
            )
            result = await runtime.registry.execute("mcp", state=state, mcp_manager=runtime.mcp_manager)
        else:
            kwargs: dict[str, Any] = {"query": plan.sub_query or question}
            if plan.route == "rag":
                kwargs["workspace_id"] = workspace_id
            elif plan.route == "sql":
                kwargs["llm"] = runtime.llm
            result = await runtime.registry.execute(plan.route, **kwargs)
        if isinstance(result, dict):
            return list(result.get("evidence") or [])
        return list(result or [])

    async def _compose(
        self,
        question: str,
        evidence: list[str],
        memory_notes: list[str],
        llm,
        context_messages: list[Any] | None = None,
    ) -> str:
        """答案合成：无 LLM 走模板拼装，有 LLM 走证据约束提示（与 graph._compose 同源）。

        ``context_messages``：compaction 摘要消息（plan() 写入 notes["messages"]），
        作为「对话上下文」并入提示，使摘要真正参与合成（P1 修正：此前摘要被丢弃）。
        """
        if llm is None:
            parts = [f"（无 LLM 模式）针对问题「{question}」收集到的证据："]
            if evidence:
                parts.extend(f"- {e}" for e in evidence)
            else:
                parts.append("- 无")
            if memory_notes:
                parts.append("相关历史记忆：" + "；".join(memory_notes))
            if context_messages:
                parts.append("对话上下文：" + "；".join(_message_content(m) for m in context_messages))
            return "\n".join(parts)
        blocks = [f"## 证据\n{i}. {e}" for i, e in enumerate(evidence, start=1)] or ["## 证据\n（无）"]
        if memory_notes:
            blocks.append("## 历史记忆\n" + "\n".join(f"- {m}" for m in memory_notes))
        if context_messages:
            context_text = "\n".join(
                _message_content(m) for m in context_messages
            )
            blocks.append("## 对话上下文\n" + context_text)
        blocks.append(f"## 问题\n{question}")
        raw = await llm.ainvoke(
            [
                {"role": "system", "content": _SYNTHESIZE_PROMPT},
                {"role": "user", "content": "\n\n".join(blocks)},
            ]
        )
        return raw.content if hasattr(raw, "content") else str(raw)
