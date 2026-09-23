"""ContextGovernor（Context Governance）：统一编排管道。

把现有的零散组件（ContextSelector → MemoryRetriever → ContextAssembler）串成
统一管道，并在召回后、组装前插入三道治理关卡：

    Select → Recall → Authorize → Validate → QualityScore → Assemble → CompiledContext

Governor 是 Context 治理的唯一入口。向后兼容：Governor 不可用时（retriever=None）
退化为直接调 Assembler，行为与旧路径完全一致。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from agent_runtime.context.assembler import AssemblyReport, ContextAssembler
from agent_runtime.context.authorizer import AuthorizationReport, ContextAuthorizer
from agent_runtime.context.quality import ContextQualityScorer, QualityReport
from agent_runtime.context.validator import ContextValidator, ValidationReport
from agent_runtime.memory_types import (
    ContextSelector,
    MemoryRecallRequest,
    MemoryRetriever,
)

logger = logging.getLogger(__name__)


@dataclass
class CompiledContext:
    """Governor 编译结果：最终消息 + 全链路治理报告。"""

    messages: list[Any]
    assembly_report: AssemblyReport
    quality_report: QualityReport = field(default_factory=QualityReport)
    validation_report: ValidationReport = field(default_factory=ValidationReport)
    authorization_report: AuthorizationReport = field(default_factory=AuthorizationReport)
    recalled_count: int = 0
    authorized_count: int = 0
    validated_count: int = 0
    selection_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "messages_count": len(self.messages),
            "assembly": self.assembly_report.to_dict(),
            "quality": self.quality_report.to_dict(),
            "validation": self.validation_report.to_dict(),
            "authorization": self.authorization_report.to_dict(),
            "recalled_count": self.recalled_count,
            "authorized_count": self.authorized_count,
            "validated_count": self.validated_count,
            "selection_reason": self.selection_reason,
        }


class ContextGovernor:
    """Context 治理统一编排管道。

    用法::

        governor = ContextGovernor(
            assembler=assembler,
            retriever=retriever,
            selector=selector,
            validator=ContextValidator(),
            authorizer=ContextAuthorizer(),
            quality_scorer=ContextQualityScorer(),
        )
        compiled = await governor.compile(
            query="如何配置 SSL",
            user_message="帮我配置 SSL 证书",
            system_prompt="你是一个运维助手",
            state=agent_context.snapshot(),
            task_type="execute",
            tenant_id="t1",
            user_id="u1",
            conversation=recent_messages,
            tool_results=[...],
        )
        messages = compiled.messages  # 送进 LLM

    向后兼容：retriever=None 时跳过召回，直接走 Assembler（旧路径）。
    """

    def __init__(
        self,
        *,
        assembler: ContextAssembler,
        retriever: MemoryRetriever | None = None,
        selector: ContextSelector | None = None,
        validator: ContextValidator | None = None,
        authorizer: ContextAuthorizer | None = None,
        quality_scorer: ContextQualityScorer | None = None,
    ) -> None:
        self.assembler = assembler
        self.retriever = retriever
        self.selector = selector or ContextSelector()
        self.validator = validator
        self.authorizer = authorizer
        self.quality_scorer = quality_scorer

    async def compile(
        self,
        *,
        query: str = "",
        user_message: str = "",
        system_prompt: str = "",
        state: dict[str, Any] | None = None,
        task_type: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        workspace_id: str | None = None,
        execution_id: str | None = None,
        conversation: list[Any] | None = None,
        tool_results: list[Any] | None = None,
        tool_defs: list[dict[str, Any]] | None = None,
        top_k: int = 10,
    ) -> CompiledContext:
        """统一编译入口：Select → Recall → Authorize → Validate → Score → Assemble。"""
        memory_strings: list[str] = []
        quality_report = QualityReport()
        validation_report = ValidationReport()
        authorization_report = AuthorizationReport()
        selection_reason = ""

        if self.retriever is not None and query:
            # 1. Select：按任务类型选 Memory 类型
            selection = self.selector.select(task_type=task_type, execution_id=execution_id)
            selection_reason = selection.reason

            # 2. Recall：统一召回
            request = MemoryRecallRequest(
                query=query,
                execution_id=execution_id,
                tenant_id=tenant_id,
                user_id=user_id,
                workspace_id=workspace_id,
                task_type=task_type,
                top_k=top_k,
                categories=selection.categories,
            )
            recalled = await self.retriever.recall(request)
            recalled_count = len(recalled)

            # 3. Authorize：Memory 级权限过滤
            if self.authorizer is not None and recalled:
                authorization_report = self.authorizer.authorize(
                    recalled,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    workspace_id=workspace_id,
                )
                authorized = self.authorizer.apply(recalled, authorization_report)
            else:
                authorized = recalled
                authorization_report = AuthorizationReport(
                    allowed_count=len(recalled),
                )

            # 4. Validate：跨来源一致性校验
            if self.validator is not None and authorized:
                validation_report = self.validator.validate(authorized, state=state)
                validated = self.validator.apply(authorized, validation_report)
            else:
                validated = authorized

            # 5. Quality Score
            if self.quality_scorer is not None and validated:
                quality_report = self.quality_scorer.score(validated, query=query)
                validated = _sort_by_quality(validated, quality_report)

            memory_strings = [_get_content(m) for m in validated]
            authorized_count = authorization_report.allowed_count
            validated_count = len(validated)
        else:
            recalled_count = 0
            authorized_count = 0
            validated_count = 0

        # 6. Assemble：ContextAssembler 组装最终消息
        messages, assembly_report = await self.assembler.assemble(
            user_message=user_message,
            system_prompt=system_prompt,
            tool_defs=tool_defs,
            snapshot=state,
            conversation=conversation,
            tool_results=tool_results,
            memories=memory_strings or None,
        )

        return CompiledContext(
            messages=messages,
            assembly_report=assembly_report,
            quality_report=quality_report,
            validation_report=validation_report,
            authorization_report=authorization_report,
            recalled_count=recalled_count,
            authorized_count=authorized_count,
            validated_count=validated_count,
            selection_reason=selection_reason,
        )

    async def govern_memories(
        self,
        *,
        query: str,
        state: dict[str, Any] | None = None,
        task_type: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        workspace_id: str | None = None,
        execution_id: str | None = None,
        top_k: int = 10,
    ) -> tuple[list[str], CompiledContext]:
        """只做召回 + 治理（不调 Assembler），返回 (memory_strings, report)。

        供 Planner 自行管理 prompt 组装的场景使用——Governor 只负责
        Select → Recall → Authorize → Validate → Score，
        返回治理后的 memory 字符串列表，由调用方注入 PlannerContext。
        """
        if self.retriever is None or not query:
            return [], CompiledContext(
                messages=[],
                assembly_report=AssemblyReport(
                    model_window=0, input_budget=0
                ),
            )

        # 1. Select
        selection = self.selector.select(task_type=task_type, execution_id=execution_id)

        # 2. Recall
        request = MemoryRecallRequest(
            query=query,
            execution_id=execution_id,
            tenant_id=tenant_id,
            user_id=user_id,
            workspace_id=workspace_id,
            task_type=task_type,
            top_k=top_k,
            categories=selection.categories,
        )
        recalled = await self.retriever.recall(request)

        # 3. Authorize
        if self.authorizer is not None and recalled:
            auth_report = self.authorizer.authorize(
                recalled,
                tenant_id=tenant_id,
                user_id=user_id,
                workspace_id=workspace_id,
            )
            authorized = self.authorizer.apply(recalled, auth_report)
        else:
            auth_report = AuthorizationReport(allowed_count=len(recalled))
            authorized = recalled

        # 4. Validate
        if self.validator is not None and authorized:
            val_report = self.validator.validate(authorized, state=state)
            validated = self.validator.apply(authorized, val_report)
        else:
            val_report = ValidationReport()
            validated = authorized

        # 5. Quality Score
        if self.quality_scorer is not None and validated:
            qual_report = self.quality_scorer.score(validated, query=query)
            validated = _sort_by_quality(validated, qual_report)
        else:
            qual_report = QualityReport()

        memory_strings = [_get_content(m) for m in validated]
        report = CompiledContext(
            messages=[],
            assembly_report=AssemblyReport(
                model_window=0, input_budget=0
            ),
            quality_report=qual_report,
            validation_report=val_report,
            authorization_report=auth_report,
            recalled_count=len(recalled),
            authorized_count=auth_report.allowed_count,
            validated_count=len(validated),
            selection_reason=selection.reason,
        )
        return memory_strings, report


def _get_content(mem: Any) -> str:
    """从 MemoryRecallResult 或 dict 或 str 提取 content。"""
    if hasattr(mem, "content"):
        return str(mem.content)
    if isinstance(mem, dict):
        return str(mem.get("content", ""))
    return str(mem)


def _sort_by_quality(memories: list[Any], report: QualityReport) -> list[Any]:
    """按质量分降序排序 Memory 列表。"""
    if len(memories) != len(report.scores):
        return memories
    paired = list(zip(memories, report.scores))
    paired.sort(key=lambda x: -x[1].overall)
    return [m for m, _ in paired]
