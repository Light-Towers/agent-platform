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
from agent_runtime.planner.context_manager import render_snapshot_prompt
from agent_runtime.planner.protocol import (
    ExecutionContext,
    Plan,
    Planner,
    PlannerContext,
    PlannerRuntime,
    StreamEvent,
)

from agent_server.agent.intent_bridge import l1_route_hint_async
from agent_server.agent.router import decide_route
from agent_server.agent.state import AgentState
from agent_server.config import get_settings
from agent_server.context import build_context_assembler, conversation_cap
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
                    question=question,
                    workspace_id=ctx.workspace_id,
                    user_id=ctx.user_id,
                    last_snapshot=ctx.last_snapshot,
                )
            question = guard["redacted_text"]

        # 上下文压缩：多轮会话 token 超阈值时摘要旧消息（与 graph.route_node 同源，
        # 双链路收敛为统一 assembler 入口，行为兼容旧阈值语义）
        if settings.compaction_enabled and ctx.llm is not None:
            model_name = getattr(ctx.llm, "model_name", None) or getattr(ctx.llm, "model", None)
            assembler = build_context_assembler(
                settings, llm=ctx.llm, model=model_name,
            )
            compacted, _report = await assembler.assemble_conversation_only(
                messages=ctx.messages,
                user_message=question,
                conversation_cap=conversation_cap(settings),
            )
            if compacted is not None:
                return Plan(
                    route="direct",
                    sub_query=question,
                    reason="上下文已压缩，重新路由",
                    question=question,
                    workspace_id=ctx.workspace_id,
                    user_id=ctx.user_id,
                    messages=compacted,
                    compacted=True,
                    last_snapshot=ctx.last_snapshot,
                )

        # L1 轻量 short-circuit：高置信 chitchat 直答（与 graph.route_node 同源，eval 基线不受影响）
        # WS-6：async 入口，嵌入计算不阻塞事件循环
        l1_hint = await l1_route_hint_async(question)
        if l1_hint is not None:
            return Plan(
                route=l1_hint,
                sub_query=question,
                reason="L1 chitchat short-circuit",
                question=question,
                workspace_id=ctx.workspace_id,
                user_id=ctx.user_id,
                last_snapshot=ctx.last_snapshot,
            )

        # LLM 主路由：失败自动回退确定性启发式（decide_route 内部处理）
        decision = await decide_route(ctx.llm, question)
        return Plan(
            route=decision.capability,
            sub_query=decision.sub_query,
            reason=decision.reason,
            question=question,
            workspace_id=ctx.workspace_id,
            user_id=ctx.user_id,
            mcp_server=ctx.mcp_server,
            mcp_tool=ctx.mcp_tool,
            mcp_params=ctx.mcp_params,
            last_snapshot=ctx.last_snapshot,
        )

    async def execute(
        self,
        plan: Plan,
        runtime: PlannerRuntime,
        ctx: ExecutionContext | None = None,
    ) -> AsyncIterator[StreamEvent]:
        settings = get_settings()
        question = plan.question or plan.sub_query or ""
        workspace_id = plan.workspace_id

        yield StreamEvent(type="route", payload={"capability": plan.route, "reason": plan.reason})
        if plan.route == "blocked":
            yield StreamEvent(type="answer", payload={"text": "抱歉，您的输入包含不安全的内容，请重新描述。"})
            return

        # 记忆召回（决策后执行期；pool 为 None 时跳过——memory 依赖 DB 池）
        # 经 MemoryGate 门控：去重/冲突消解/预算内取 top（P2 接线，settings.memory_gate_top_k 控制条数）
        memory_notes: list[str] = []
        if settings.memory_enabled and runtime.pool is not None:
            if getattr(settings, "memory_gate_top_k", 5) > 0:
                from agent_runtime.context.memory_gate import MemoryGate, gate_recall

                gate = MemoryGate(top_k=settings.memory_gate_top_k)
                memory_notes = await gate_recall(
                    lambda question: recall(runtime.pool, workspace_id, question),
                    question,
                    gate=gate,
                )
            else:
                memory_notes = await recall(runtime.pool, workspace_id, question)
            if memory_notes:
                yield StreamEvent(type="memory", payload={"notes": memory_notes})

        # 能力调用 + 反思重试：证据为空且未到上限时回到 plan 重新决策（与 synthesize_node 同源）
        # 统一执行边界（P0 路径A）：能力调用经 execution() + delegate 受组合治理，
        # 与 graph 控制平面共享同一执行边界契约。记忆召回/合成/沉淀是 Planner 编排，
        # 非 Skill 组合，不走 delegate；反思重试在边界内顺序调用，步数累计（max_steps=20 充裕）。
        async with runtime.execution():
            iterations = plan.iterations
            original_snapshot = plan.last_snapshot
            while True:
                evidence = await self._run_capability(plan, runtime, workspace_id, question)
                yield StreamEvent(
                    type="evidence",
                    payload={"node": plan.route, "count": len(evidence), "preview": evidence[0][:200] if evidence else ""},
                )
                has_real = evidence and not any(e.startswith(_EMPTY_EVIDENCE_MARKERS) for e in evidence)
                if not has_real and plan.route != "direct" and iterations < settings.max_iterations:
                    iterations += 1
                    plan.iterations = iterations
                    previous_route = plan.route
                    plan = await self.plan(
                        PlannerContext(
                            question=question,
                            workspace_id=workspace_id,
                            user_id=plan.user_id,
                            messages=[],
                            llm=runtime.llm,
                        )
                    )
                    # re-plan 新建的 Plan 不携带原快照，回填避免丢失（WS-2）
                    if not plan.last_snapshot:
                        plan.last_snapshot = original_snapshot
                    yield StreamEvent(
                        type="replan",
                        payload={
                            "iteration": iterations,
                            "from_route": previous_route,
                            "to_route": plan.route,
                            "reason": "evidence_insufficient",
                        },
                    )
                    continue
                break

            # 合成 + 记忆沉淀（与 synthesize_node 同源）
            # compaction 路径：plan() 把摘要写入 messages，这里消费它作为合成上下文
            context_messages = plan.messages
            answer = await self._compose(
                question,
                evidence,
                memory_notes,
                runtime.llm,
                context_messages,
                snapshot=plan.last_snapshot,
            )
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
        """按 Plan.route 经 runtime.delegate（skill_guard 组合治理）执行能力，结果归一化为 evidence 列表。"""
        if plan.route == "direct":
            return []
        if plan.route == "mcp":
            if runtime.mcp_manager is None:
                return ["MCP 未启用"]
            state = AgentState(
                question=question,
                sub_query=plan.sub_query or question,
                user_id=plan.user_id,
                workspace_id=workspace_id,
                mcp_server=plan.mcp_server,
                mcp_tool=plan.mcp_tool,
                mcp_params=plan.mcp_params,
            )
            result = await runtime.delegate("mcp", state=state, mcp_manager=runtime.mcp_manager)
        else:
            kwargs: dict[str, Any] = {"query": plan.sub_query or question}
            if plan.route == "rag":
                kwargs["workspace_id"] = workspace_id
            elif plan.route == "sql":
                kwargs["llm"] = runtime.llm
            result = await runtime.delegate(plan.route, **kwargs)
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
        snapshot: dict[str, Any] | None = None,
    ) -> str:
        """答案合成：无 LLM 走模板拼装，有 LLM 走证据约束提示（与 graph._compose 同源）。

        ``context_messages``：compaction 摘要消息（plan() 写入 notes["messages"]），
        作为「对话上下文」并入提示，使摘要真正参与合成（P1 修正：此前摘要被丢弃）。
        ``snapshot``：上一轮执行的结构化快照（WS-2），经 ``render_snapshot_prompt``
        渲染为「任务状态」块结构化注入，不进对话历史存储。
        """
        snapshot_text = render_snapshot_prompt(snapshot)
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
            if snapshot_text:
                parts.append(snapshot_text)
            return "\n".join(parts)
        blocks = [f"## 证据\n{i}. {e}" for i, e in enumerate(evidence, start=1)] or ["## 证据\n（无）"]
        if memory_notes:
            blocks.append("## 历史记忆\n" + "\n".join(f"- {m}" for m in memory_notes))
        if context_messages:
            context_text = "\n".join(
                _message_content(m) for m in context_messages
            )
            blocks.append("## 对话上下文\n" + context_text)
        if snapshot_text:
            blocks.append("## 任务状态\n" + snapshot_text)
        blocks.append(f"## 问题\n{question}")
        raw = await llm.ainvoke(
            [
                {"role": "system", "content": _SYNTHESIZE_PROMPT},
                {"role": "user", "content": "\n\n".join(blocks)},
            ]
        )
        return raw.content if hasattr(raw, "content") else str(raw)
