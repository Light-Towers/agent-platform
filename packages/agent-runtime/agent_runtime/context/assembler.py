"""ContextAssembler（Plan-F Context Pipeline 核心）：统一上下文组装入口。

管线（collect → rank → budget → compress → assemble）：

1. **Collect**：从四类来源收集候选块（system/当前用户消息/task snapshot/对话历史/
   tool results/memory/execution snapshot/tool_defs）；
2. **Rank**：按优先级排序（不可被裁掉的顺序：system/policy > 当前用户消息 > task
   snapshot > 最近原始消息 > tool results > semantic memory > 旧对话历史）；
3. **Budget**：按 ``ContextBudget`` 分层分配，未用余量回流 conversation / tool_results；
4. **Compress**：超预算块逐个处理——对话走 compact（LLM 摘要），tool results 走
   ToolResultCompressor（外置），memory 走 MemoryGate，旧历史截断；
5. **Trim + Assemble**：产出最终消息列表 + ``AssemblyReport``（可观测性）。

``Assembler`` 是唯一组装入口；token 计量全部走 ``agent_core.tokenizer``，
不新造尺子；snapshot 直接读 ``ContextManager.snapshot()`` 的 task/execution 层，
结构化注入而非靠消息流残留。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from agent_core.tokenizer import count_messages, count_tokens

from agent_runtime.context.budget import ContextBudget, Layer
from agent_runtime.context.compact import compact_messages
from agent_runtime.context.memory_gate import MemoryGate
from agent_runtime.context.tool_result import ToolResultCompressor
from agent_runtime.otel import get_otel_tracer

logger = logging.getLogger(__name__)

# 各层默认优先级（越高越不可被裁掉；相同优先级按层内顺序保留）
_LAYER_PRIORITY: dict[Layer, int] = {
    Layer.SYSTEM: 100,
    Layer.TASK: 80,
    Layer.CONVERSATION: 70,
    Layer.TOOL_DEFS: 60,
    Layer.MEMORY: 50,
    Layer.TOOL_RESULTS: 40,
    Layer.EXECUTION: 30,
}

# 对话层压缩失败后的兜底：只保留最近 N 条原始消息
_DROP_KEEP_RECENT = 4


@dataclass
class AssemblyBlock:
    """候选块：来源层 + 优先级 + 内容 + token 数 + 处理动作。"""

    layer: Layer
    priority: int
    content: Any  # str 或 dict 消息
    tokens: int = 0
    action: str = "keep"  # keep | compacted | truncated | dropped | externalized
    ref: str = ""


@dataclass
class AssemblyReport:
    """组装审计记录：每层 token 占用 / 占比 / 裁剪动作，供可观测性消费。"""

    model_window: int
    input_budget: int
    total_tokens: int = 0
    layers: dict[str, int] = field(default_factory=dict)
    layer_ratio: dict[str, float] = field(default_factory=dict)
    actions: list[dict[str, Any]] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    messages_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_window": self.model_window,
            "input_budget": self.input_budget,
            "total_tokens": self.total_tokens,
            "layers": dict(self.layers),
            "layer_ratio": dict(self.layer_ratio),
            "actions": list(self.actions),
            "dropped": list(self.dropped),
            "messages_count": self.messages_count,
        }

    def log(self, tag: str = "context_assembly") -> None:
        """结构化日志输出（观测：每层 token 分布一眼可见）。"""
        logger.info(
            "CONTEXT_ASSEMBLY tag=%s total_tokens=%d/%d messages=%d actions=%d dropped=%d",
            tag,
            self.total_tokens,
            self.input_budget,
            self.messages_count,
            len(self.actions),
            len(self.dropped),
        )
        for layer, tokens in self.layers.items():
            logger.debug("  %s: %d tokens (%.1f%%)", layer, tokens, self.layer_ratio.get(layer, 0))


def _as_message(block: AssemblyBlock) -> dict[str, str]:
    """块 → dict 消息（compressed/externalized 块也统一为文本消息）。"""
    text = block.content if isinstance(block.content, str) else _block_text(block.content)
    if block.layer == Layer.SYSTEM or block.action in ("compacted", "externalized"):
        return {"role": "system", "content": text}
    if block.layer == Layer.TASK:
        return {"role": "system", "content": text}
    return {"role": "user", "content": text}


def _block_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return str(content.get("content", content))
    return str(content)


class ContextAssembler:
    """统一上下文组装器：collect → rank → budget → compress → assemble。

    用法::

        assembler = ContextAssembler(ContextBudget(model_window=128_000), llm=llm)
        messages, report = await assembler.assemble(
            user_message="...",
            system_prompt="...",
            conversation=recent_messages,
            tool_results=[...],
            snapshot=agent_context_snapshot,  # AgentContext.snapshot() 输出
        )
    """

    def __init__(
        self,
        budget: ContextBudget,
        *,
        llm: Any = None,
        model: str | None = None,
        tool_result_store: str | None = None,
        memory_gate: MemoryGate | None = None,
        layer_priority: dict[Layer, int] | None = None,
    ) -> None:
        self.budget = budget
        self.llm = llm
        self.model = model
        self._tool_compressor = ToolResultCompressor(
            max_tokens=int(budget.ratio_of(Layer.TOOL_RESULTS) * budget.input_budget),
            store_dir=tool_result_store,
            model=model,
        )
        self._memory_gate = memory_gate or MemoryGate(top_k=5)
        self._layer_priority = dict(layer_priority or _LAYER_PRIORITY)
        self._report_actions: list[dict[str, Any]] = []
        self.dropped_refs: list[str] = []

    # ---------- 1+2. collect + rank ----------

    def _collect(
        self,
        *,
        user_message: str = "",
        system_prompt: str = "",
        tool_defs: list[dict[str, Any]] | None = None,
        snapshot: dict[str, Any] | None = None,
        conversation: list[Any] | None = None,
        tool_results: list[Any] | None = None,
        memories: list[str] | None = None,
    ) -> list[AssemblyBlock]:
        blocks: list[AssemblyBlock] = []

        if system_prompt:
            blocks.append(
                AssemblyBlock(
                    Layer.SYSTEM,
                    self._layer_priority[Layer.SYSTEM],
                    system_prompt,
                    count_tokens(system_prompt, self.model),
                )
            )

        if user_message:
            blocks.append(
                AssemblyBlock(
                    Layer.CONVERSATION,
                    self._layer_priority[Layer.CONVERSATION] + 10,  # 当前消息最高优先级
                    {"role": "user", "content": user_message},
                    count_tokens(user_message, self.model),
                )
            )

        if tool_defs:
            defs_text = "\n".join(
                f"- {d.get('name', '')}: {d.get('description', '')}" for d in tool_defs
            )
            blocks.append(
                AssemblyBlock(
                    Layer.TOOL_DEFS,
                    self._layer_priority[Layer.TOOL_DEFS],
                    defs_text,
                    count_tokens(defs_text, self.model),
                )
            )

        if snapshot:
            # snapshot 注入 task/execution 层（结构化，非消息流残留）
            task = snapshot.get("task") or {}
            task_text = "任务目标: {goal}\n已完成: {completed}\n待办: {pending}\n约束: {constraints}".format(
                goal=task.get("goal", ""),
                completed=", ".join(task.get("completed_steps", []) or []),
                pending=", ".join(task.get("pending", []) or []),
                constraints=str(task.get("constraints", {})),
            )
            blocks.append(
                AssemblyBlock(
                    Layer.TASK,
                    self._layer_priority[Layer.TASK],
                    task_text,
                    count_tokens(task_text, self.model),
                )
            )
            execution = snapshot.get("execution") or {}
            if execution.get("outputs") or execution.get("errors"):
                exec_text = (
                    "执行状态:\n- 输出: {outputs}\n- 错误: {errors}".format(
                        outputs=json_dumps(execution.get("outputs", {})),
                        errors=json_dumps(execution.get("errors", {})),
                    )
                )
                blocks.append(
                    AssemblyBlock(
                        Layer.EXECUTION,
                        self._layer_priority[Layer.EXECUTION],
                        exec_text,
                        count_tokens(exec_text, self.model),
                    )
                )

        for msg in conversation or []:
            blocks.append(
                AssemblyBlock(
                    Layer.CONVERSATION,
                    self._layer_priority[Layer.CONVERSATION],
                    msg,
                    count_messages([msg], self.model),
                )
            )

        for result in tool_results or []:
            text = result if isinstance(result, str) else json_dumps(result)
            blocks.append(
                AssemblyBlock(
                    Layer.TOOL_RESULTS,
                    self._layer_priority[Layer.TOOL_RESULTS],
                    text,
                    count_tokens(text, self.model),
                )
            )

        for mem in memories or []:
            blocks.append(
                AssemblyBlock(
                    Layer.MEMORY,
                    self._layer_priority[Layer.MEMORY],
                    mem,
                    count_tokens(mem, self.model),
                )
            )

        return blocks

    # ---------- 3. budget ----------

    def _group_by_layer(self, blocks: list[AssemblyBlock]) -> dict[Layer, list[AssemblyBlock]]:
        grouped: dict[Layer, list[AssemblyBlock]] = {}
        for block in blocks:
            grouped.setdefault(block.layer, []).append(block)
        return grouped

    # ---------- 4. compress ----------

    async def _compress_conversation(
        self, blocks: list[AssemblyBlock], cap: int
    ) -> list[AssemblyBlock]:
        """对话层超预算：LLM 摘要（compact_messages），失败则保留最近 N 条。"""
        total = sum(b.tokens for b in blocks)
        if total <= cap:
            return blocks
        if self.llm is None:
            # 无 LLM：保留最近 N 条（当前消息优先已在 collect 中置于最前）
            kept = blocks[:_DROP_KEEP_RECENT]
            for b in blocks[_DROP_KEEP_RECENT:]:
                b.action = "truncated"
                self._report_actions.append(
                    {"layer": str(b.layer), "action": "truncated", "tokens": b.tokens}
                )
            return kept
        messages = [_block_text(b.content) for b in blocks]
        compacted, err = await compact_messages(
            [{"role": "user", "content": m} for m in messages], self.llm, self.model
        )
        if err is not None:
            kept = blocks[:_DROP_KEEP_RECENT]
            for b in blocks[_DROP_KEEP_RECENT:]:
                b.action = "truncated"
                self._report_actions.append(
                    {"layer": str(b.layer), "action": "truncated", "tokens": b.tokens}
                )
            return kept
        summary = compacted[0]["content"] if compacted else ""
        block = AssemblyBlock(
            Layer.CONVERSATION,
            self._layer_priority[Layer.CONVERSATION],
            summary,
            count_tokens(summary, self.model),
            action="compacted",
        )
        self._report_actions.append(
            {"layer": str(Layer.CONVERSATION), "action": "compacted", "tokens": block.tokens}
        )
        return [block]

    def _compress_tool_results(
        self, blocks: list[AssemblyBlock], cap: int
    ) -> list[AssemblyBlock]:
        """Tool results 层超预算：逐块压缩（外置），保头部少量块。"""
        total = sum(b.tokens for b in blocks)
        if total <= cap:
            return blocks
        budget_left = cap
        out: list[AssemblyBlock] = []
        for block in blocks:
            if budget_left <= 0:
                block.action = "dropped"
                self._report_actions.append(
                    {"layer": str(block.layer), "action": "dropped", "tokens": block.tokens}
                )
                self.dropped_refs.append(str(block.ref))
                continue
            compressed = self._tool_compressor.compress(block.content)
            if compressed["truncated"]:
                block.action = "externalized"
                block.content = compressed["text"]
                block.ref = compressed["ref"]
                block.tokens = count_tokens(compressed["text"], self.model)
                self._report_actions.append(
                    {"layer": str(block.layer), "action": "externalized", "ref": compressed["ref"]}
                )
            if block.tokens <= budget_left:
                out.append(block)
                budget_left -= block.tokens
            else:
                block.action = "dropped"
                self._report_actions.append(
                    {"layer": str(block.layer), "action": "dropped", "tokens": block.tokens}
                )
        return out

    def _trim_to_cap(
        self, blocks: list[AssemblyBlock], cap: int
    ) -> list[AssemblyBlock]:
        """通用裁剪：按层内顺序保留前若干块，使其总量 <= cap。"""
        total = sum(b.tokens for b in blocks)
        if total <= cap:
            return blocks
        out: list[AssemblyBlock] = []
        acc = 0
        for block in blocks:
            if acc + block.tokens > cap:
                block.action = "dropped"
                self._report_actions.append(
                    {"layer": str(block.layer), "action": "dropped", "tokens": block.tokens}
                )
                continue
            out.append(block)
            acc += block.tokens
        return out

    # ---------- 5. assemble ----------

    async def assemble(
        self,
        *,
        user_message: str = "",
        system_prompt: str = "",
        tool_defs: list[dict[str, Any]] | None = None,
        snapshot: dict[str, Any] | None = None,
        conversation: list[Any] | None = None,
        tool_results: list[Any] | None = None,
        memories: list[str] | None = None,
    ) -> tuple[list[Any], AssemblyReport]:
        """统一组装入口：返回 (最终消息列表, AssemblyReport)。"""
        self._report_actions = []
        self.dropped_refs: list[str] = []
        blocks = self._collect(
            user_message=user_message,
            system_prompt=system_prompt,
            tool_defs=tool_defs,
            snapshot=snapshot,
            conversation=conversation,
            tool_results=tool_results,
            memories=memories,
        )

        # 预算（动态：按各层当前用量回流）
        used = {layer: sum(b.tokens for b in bs) for layer, bs in self._group_by_layer(blocks).items()}
        caps = self.budget.effective_caps(used)

        # 分层压缩/裁剪
        grouped = self._group_by_layer(blocks)
        final_blocks: list[AssemblyBlock] = []
        for layer, layer_blocks in grouped.items():
            cap = caps[layer]
            if layer == Layer.CONVERSATION:
                layer_blocks = await self._compress_conversation(layer_blocks, cap)
            elif layer == Layer.TOOL_RESULTS:
                layer_blocks = self._compress_tool_results(layer_blocks, cap)
            else:
                layer_blocks = self._trim_to_cap(layer_blocks, cap)
            final_blocks.extend(layer_blocks)

        # 按优先级降序组装（system 最前）
        final_blocks.sort(key=lambda b: (-b.priority, list(Layer).index(b.layer)))
        messages = [_as_message(b) for b in final_blocks]

        report = self._build_report(messages, caps)
        report.actions = list(self._report_actions)
        report.dropped = list(self.dropped_refs)
        report.log()
        self._emit_span("assemble", report, caps, messages)
        return messages, report

    def _build_report(self, messages: list[Any], caps: dict[Layer, int]) -> AssemblyReport:
        report = AssemblyReport(
            model_window=self.budget.model_window,
            input_budget=self.budget.input_budget,
            total_tokens=count_messages(messages, self.model),
            layers={str(k): v for k, v in caps.items()},
            messages_count=len(messages),
        )
        for layer, cap in caps.items():
            report.layer_ratio[str(layer)] = round(cap / self.budget.input_budget, 4) if self.budget.input_budget else 0.0
        return report

    async def assemble_conversation_only(
        self,
        *,
        messages: list[Any],
        user_message: str = "",
        snapshot: dict[str, Any] | None = None,
        conversation_cap: int | None = None,
    ) -> tuple[list[Any] | None, AssemblyReport]:
        """单层组装入口：只组装 conversation 层（路由期压缩决策）。

        用于 graph.route_node / deterministic.plan 两处对旧 ``should_compact +
        compact_messages`` 的收敛——统一走 assembler，压缩语义与旧实现一致
        （超阈值 + LLM 摘要 + 保留最近 N 条原始消息）。

        - ``conversation_cap`` 缺省用 budget 的 conversation 层上限；传入时
          覆盖（调用方可传旧阈值保持行为不变）。
        - 返回 ``(compacted_messages, report)``：未触发压缩或压缩失败降级时
          ``compacted_messages`` 为 None（调用方继续正常路由）。
        """
        self._report_actions = []
        self.dropped_refs = []
        blocks = self._collect(user_message=user_message, conversation=messages, snapshot=snapshot)
        conv_blocks = [b for b in blocks if b.layer == Layer.CONVERSATION]
        total = sum(b.tokens for b in conv_blocks)
        cap = (
            conversation_cap
            if conversation_cap is not None
            else self.budget.static_caps()[Layer.CONVERSATION]
        )

        ordered = sorted(blocks, key=lambda b: (-b.priority, list(Layer).index(b.layer)))
        fallback_report = self._build_report([_as_message(b) for b in ordered], self.budget.static_caps())
        fallback_report.actions = list(self._report_actions)

        if total <= cap or self.llm is None:
            return None, fallback_report

        compressed = await self._compress_conversation(conv_blocks, cap)
        compacted_blocks = [b for b in compressed if b.action == "compacted"]
        if not compacted_blocks:
            return None, fallback_report

        summary = _block_text(compacted_blocks[0].content)
        recent = list(messages[-_DROP_KEEP_RECENT:]) if messages else []
        result = [{"role": "system", "content": summary}] + recent
        report = self._build_report(result, self.budget.static_caps())
        report.actions = list(self._report_actions)
        self._emit_span("assemble_conversation_only", report, self.budget.static_caps(), result)
        return result, report

    def _emit_span(
        self,
        span_name: str,
        report: AssemblyReport,
        caps: dict[Layer, int],
        messages: list[Any],
    ) -> None:
        """可观测性（P2）：把组装结果写进当前 OTel span（未启用时 NoOp）。

        属性遵循 GenAI 语义约定：``gen_ai.usage.input_tokens`` 计输入 token，
        其余为 Agent 平台自定义约定（``agent.context.*``）。不含消息全文，避免敏感内容入链路。
        """
        span = get_otel_tracer().start_span(span_name)
        try:
            span.set_attribute("gen_ai.usage.input_tokens", report.total_tokens)
            span.set_attribute("gen_ai.usage.input_cost", report.total_tokens)
            span.set_attribute("agent.context.model_window", self.budget.model_window)
            span.set_attribute("agent.context.input_budget", self.budget.input_budget)
            span.set_attribute("agent.context.messages_count", len(messages))
            span.set_attribute("agent.context.caps", json_dumps(caps))
            if report.actions:
                span.set_attribute("agent.context.actions", json_dumps(report.actions))
        finally:
            span.end()


def json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, default=str)