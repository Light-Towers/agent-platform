"""agent_server 侧 Context Pipeline 装配（Plan-F）：从 settings 构建统一组装器。

把 graph.py route_node 与 planners/deterministic.py 两处重复的
``threshold + should_compact + compact_messages`` 收敛为一次
``assembler.assemble_conversation_only()`` 调用（单层入口，行为兼容旧阈值语义）。

完整多层 ``assemble()``（含 snapshot 注入 task/execution 层、tool_results 压缩、
memory 门控）供需要丰富上下文的调用方使用。
"""

from __future__ import annotations

from typing import Any

from agent_runtime.context import ContextAssembler, ContextBudget, Layer, MemoryGate

from agent_server.config import Settings


def build_context_assembler(
    settings: Settings,
    *,
    llm: Any = None,
    model: str | None = None,
    store_dir: str | None = None,
) -> ContextAssembler:
    """从 settings 构建 ``ContextAssembler``。

    - 窗口：``model_context_window``；
    - tool_results 占比：``context_budget_tool_results_ratio``；
    - 记忆门控：``memory_gate_top_k``；
    - 工具结果外置目录：``tool_result_store_dir``（空则回退到调用方传入 store_dir）。
    """
    budget = ContextBudget(
        model_window=settings.model_context_window,
        layers={
            Layer.SYSTEM: 0.05,
            Layer.TOOL_DEFS: 0.08,
            Layer.TASK: 0.06,
            Layer.CONVERSATION: 0.20,
            Layer.MEMORY: 0.08,
            Layer.TOOL_RESULTS: settings.context_budget_tool_results_ratio,
            Layer.EXECUTION: 0.18,
        },
    )
    store = settings.tool_result_store_dir or store_dir
    return ContextAssembler(
        budget,
        llm=llm,
        model=model,
        tool_result_store=store,
        memory_gate=MemoryGate(top_k=settings.memory_gate_top_k),
    )


def conversation_cap(settings: Settings) -> int:
    """旧阈值语义的 conversation 层上限（兼容原 threshold 触发时机）。

    原实现：``int(model_context_window * compaction_threshold_ratio)``。
    保留该语义使双链路收敛后行为不变（不提前/延后触发压缩）。
    """
    return int(settings.model_context_window * settings.compaction_threshold_ratio)