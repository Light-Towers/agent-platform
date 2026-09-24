"""Context Governance 测试：Validator + Authorizer + QualityScorer + Governor。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import pytest

from agent_runtime.context.authorizer import (
    ContextAuthorizer,
)
from agent_runtime.context.budget import ContextBudget
from agent_runtime.context.governor import ContextGovernor
from agent_runtime.context.quality import ContextQualityScorer
from agent_runtime.context.validator import ContextValidator
from agent_runtime.memory_types import (
    MemoryCategory,
    MemoryRecallRequest,
)

# ---------- 辅 helper ----------


@dataclass
class FakeMemory:
    """测试用 Memory（duck-type MemoryRecallResult）。"""

    content: str
    category: MemoryCategory = MemoryCategory.SEMANTIC
    source: str = "test"
    score: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)


class FakeRetriever:
    """测试用 MemoryRetriever（返回预设结果）。"""

    def __init__(self, results: list[Any]) -> None:
        self._results = results

    async def recall(self, request: MemoryRecallRequest) -> list[Any]:
        return list(self._results)


# ===================================================================
# ContextValidator
# ===================================================================


class TestContextValidator:
    def test_no_state_returns_empty_report(self):
        validator = ContextValidator()
        memories = [FakeMemory(content="hello")]
        report = validator.validate(memories, state=None)
        assert len(report.issues) == 0
        assert len(report.dropped_indices) == 0

    def test_stale_memory_detected(self):
        now = time.time()
        validator = ContextValidator(stale_threshold=100.0)
        memories = [
            FakeMemory(
                content="old fact",
                metadata={"timestamp": now - 500},
            ),
        ]
        state = {"timestamp": now}
        report = validator.validate(memories, state=state, now=now)
        assert len(report.issues) == 1
        assert report.issues[0].issue == "stale"
        assert report.issues[0].action == "downgrade"
        assert 0 in report.downgrade_factors

    def test_stale_memory_downgraded_in_apply(self):
        now = time.time()
        validator = ContextValidator(stale_threshold=100.0)
        memories = [
            FakeMemory(
                content="old fact",
                score=1.0,
                metadata={"timestamp": now - 500},
            ),
        ]
        state = {"timestamp": now}
        report = validator.validate(memories, state=state, now=now)
        filtered = validator.apply(memories, report)
        assert len(filtered) == 1
        assert filtered[0].score < 1.0

    def test_conflict_memory_dropped(self):
        validator = ContextValidator(conflict_keys=("user_preference",))
        memories = [
            FakeMemory(
                content="prefers dark mode",
                metadata={"user_preference": "dark"},
            ),
        ]
        state = {"user_preference": "light"}
        report = validator.validate(memories, state=state)
        assert len(report.issues) == 1
        assert report.issues[0].issue == "conflict"
        assert report.issues[0].action == "drop"
        assert 0 in report.dropped_indices
        filtered = validator.apply(memories, report)
        assert len(filtered) == 0

    def test_invalid_entity_dropped(self):
        validator = ContextValidator(entity_keys=("execution_id",))
        memories = [
            FakeMemory(
                content="step done",
                metadata={"execution_id": "exec-999"},
            ),
        ]
        state = {"execution_id": "exec-123"}
        report = validator.validate(memories, state=state)
        assert len(report.issues) == 1
        assert report.issues[0].issue == "invalid"
        assert 0 in report.dropped_indices

    def test_valid_memory_kept(self):
        now = time.time()
        validator = ContextValidator()
        memories = [
            FakeMemory(
                content="relevant fact",
                score=0.8,
                metadata={"timestamp": now - 10},
            ),
        ]
        state = {"timestamp": now}
        report = validator.validate(memories, state=state, now=now)
        assert len(report.issues) == 0
        filtered = validator.apply(memories, report)
        assert len(filtered) == 1
        assert filtered[0].score == 0.8

    def test_nested_state_flattened(self):
        validator = ContextValidator(conflict_keys=("task_status",))
        memories = [
            FakeMemory(
                content="task running",
                metadata={"task_status": "running"},
            ),
        ]
        state = {
            "task": {"task_status": "completed"},
        }
        report = validator.validate(memories, state=state)
        assert any(i.issue == "conflict" for i in report.issues)


# ===================================================================
# ContextAuthorizer
# ===================================================================


class TestContextAuthorizer:
    def test_shared_memory_always_allowed(self):
        authorizer = ContextAuthorizer()
        memories = [
            FakeMemory(
                content="public knowledge",
                metadata={"visibility": "shared", "tenant_id": "other"},
            ),
        ]
        report = authorizer.authorize(memories, tenant_id="t1", user_id="u1")
        assert report.allowed_count == 1
        assert report.denied_count == 0

    def test_tenant_isolation(self):
        authorizer = ContextAuthorizer()
        memories = [
            FakeMemory(
                content="tenant data",
                metadata={"visibility": "tenant", "tenant_id": "t1"},
            ),
            FakeMemory(
                content="other tenant",
                metadata={"visibility": "tenant", "tenant_id": "t2"},
            ),
        ]
        report = authorizer.authorize(memories, tenant_id="t1")
        assert report.allowed_count == 1
        assert report.denied_count == 1
        filtered = authorizer.apply(memories, report)
        assert len(filtered) == 1
        assert "tenant data" in filtered[0].content

    def test_private_memory_owner_only(self):
        authorizer = ContextAuthorizer()
        memories = [
            FakeMemory(
                content="my private note",
                metadata={
                    "visibility": "private",
                    "tenant_id": "t1",
                    "user_id": "u1",
                },
            ),
            FakeMemory(
                content="someone else private",
                metadata={
                    "visibility": "private",
                    "tenant_id": "t1",
                    "user_id": "u2",
                },
            ),
        ]
        report = authorizer.authorize(memories, tenant_id="t1", user_id="u1")
        assert report.allowed_count == 1
        assert report.denied_count == 1

    def test_workspace_isolation(self):
        authorizer = ContextAuthorizer()
        memories = [
            FakeMemory(
                content="ws1 data",
                metadata={
                    "visibility": "tenant",
                    "tenant_id": "t1",
                    "workspace_id": "ws1",
                },
            ),
            FakeMemory(
                content="ws2 data",
                metadata={
                    "visibility": "tenant",
                    "tenant_id": "t1",
                    "workspace_id": "ws2",
                },
            ),
        ]
        report = authorizer.authorize(
            memories, tenant_id="t1", workspace_id="ws1"
        )
        assert report.allowed_count == 1
        assert report.denied_count == 1

    def test_no_tenant_id_allows_all(self):
        authorizer = ContextAuthorizer()
        memories = [
            FakeMemory(
                content="data",
                metadata={"visibility": "tenant", "tenant_id": "t1"},
            ),
        ]
        report = authorizer.authorize(memories)
        assert report.allowed_count == 1

    def test_default_visibility_is_tenant(self):
        authorizer = ContextAuthorizer()
        memories = [
            FakeMemory(
                content="no visibility field",
                metadata={"tenant_id": "t2"},
            ),
        ]
        report = authorizer.authorize(memories, tenant_id="t1")
        assert report.denied_count == 1


# ===================================================================
# ContextQualityScorer
# ===================================================================


class TestContextQualityScorer:
    def test_empty_memories(self):
        scorer = ContextQualityScorer()
        report = scorer.score([], query="test")
        assert len(report.scores) == 0
        assert report.average_quality == 0.0

    def test_relevance_scoring(self):
        scorer = ContextQualityScorer()
        memories = [
            FakeMemory(content="如何配置 SSL 证书"),
            FakeMemory(content="今天天气不错"),
        ]
        report = scorer.score(memories, query="配置 SSL")
        assert report.scores[0].relevance > report.scores[1].relevance
        assert report.scores[0].overall > report.scores[1].overall

    def test_freshness_scoring(self):
        now = time.time()
        scorer = ContextQualityScorer(freshness_half_life=100.0)
        memories = [
            FakeMemory(content="recent", metadata={"timestamp": now - 1}),
            FakeMemory(content="recent", metadata={"timestamp": now - 1000}),
        ]
        report = scorer.score(memories, query="recent", now=now)
        assert report.scores[0].freshness > report.scores[1].freshness

    def test_no_timestamp_zero_freshness(self):
        scorer = ContextQualityScorer()
        memories = [FakeMemory(content="no timestamp")]
        report = scorer.score(memories, query="test")
        assert report.scores[0].freshness == 0.0

    def test_conflict_degree(self):
        scorer = ContextQualityScorer()
        memories = [
            FakeMemory(
                content="用户偏好深色主题",
                metadata={"user_preference": "dark"},
            ),
            FakeMemory(
                content="用户偏好深色主题",
                metadata={"user_preference": "light"},
            ),
        ]
        report = scorer.score(memories, query="用户偏好")
        assert report.scores[0].conflict_degree > 0
        assert report.scores[1].conflict_degree > 0

    def test_low_quality_count(self):
        scorer = ContextQualityScorer(low_quality_threshold=0.9)
        memories = [FakeMemory(content="unrelated content")]
        report = scorer.score(memories, query="something completely different")
        assert report.low_quality_count >= 0

    def test_weights_validation(self):
        with pytest.raises(ValueError, match="alpha.*beta.*gamma"):
            ContextQualityScorer(alpha=0.5, beta=0.5, gamma=0.5)

    def test_quality_report_to_dict(self):
        scorer = ContextQualityScorer()
        report = scorer.score(
            [FakeMemory(content="test")], query="test"
        )
        d = report.to_dict()
        assert "scores" in d
        assert "average_quality" in d
        assert "low_quality_count" in d


# ===================================================================
# ContextGovernor — 端到端
# ===================================================================


class TestContextGovernor:
    def _make_governor(
        self,
        memories: list[Any] | None = None,
        *,
        with_governance: bool = True,
    ) -> ContextGovernor:
        from agent_runtime.context.assembler import ContextAssembler

        budget = ContextBudget(model_window=32_000)
        assembler = ContextAssembler(budget)
        retriever = FakeRetriever(memories or []) if memories is not None else None
        return ContextGovernor(
            assembler=assembler,
            retriever=retriever,
            validator=ContextValidator() if with_governance else None,
            authorizer=ContextAuthorizer() if with_governance else None,
            quality_scorer=ContextQualityScorer() if with_governance else None,
        )

    @pytest.mark.asyncio
    async def test_no_retriever_degrades_to_assembler(self):
        governor = self._make_governor(memories=None)
        compiled = await governor.compile(
            user_message="hello",
            system_prompt="you are an assistant",
        )
        assert len(compiled.messages) > 0
        assert compiled.recalled_count == 0
        assert compiled.selection_reason == ""

    @pytest.mark.asyncio
    async def test_full_pipeline_with_governance(self):
        now = time.time()
        memories = [
            FakeMemory(
                content="SSL 配置步骤",
                score=0.9,
                metadata={
                    "visibility": "shared",
                    "tenant_id": "t1",
                    "timestamp": now,
                },
            ),
        ]
        governor = self._make_governor(memories=memories)
        compiled = await governor.compile(
            query="如何配置 SSL",
            user_message="帮我配置 SSL",
            system_prompt="运维助手",
            task_type="qa",
            tenant_id="t1",
            user_id="u1",
        )
        assert compiled.recalled_count == 1
        assert compiled.authorized_count == 1
        assert compiled.validated_count == 1
        assert len(compiled.messages) > 0
        assert "qa" in compiled.selection_reason

    @pytest.mark.asyncio
    async def test_tenant_isolation_in_pipeline(self):
        memories = [
            FakeMemory(
                content="other tenant secret",
                metadata={
                    "visibility": "tenant",
                    "tenant_id": "t2",
                },
            ),
        ]
        governor = self._make_governor(memories=memories)
        compiled = await governor.compile(
            query="secret",
            user_message="show me secrets",
            tenant_id="t1",
        )
        assert compiled.recalled_count == 1
        assert compiled.authorization_report.denied_count == 1
        assert compiled.validated_count == 0

    @pytest.mark.asyncio
    async def test_stale_memory_downgraded_in_pipeline(self):
        now = time.time()
        memories = [
            FakeMemory(
                content="very old fact",
                score=1.0,
                metadata={
                    "visibility": "shared",
                    "timestamp": now - 100000,
                },
            ),
            FakeMemory(
                content="fresh fact",
                score=0.5,
                metadata={
                    "visibility": "shared",
                    "timestamp": now,
                },
            ),
        ]
        governor = self._make_governor(memories=memories)
        compiled = await governor.compile(
            query="fact",
            user_message="tell me a fact",
            state={"timestamp": now},
        )
        assert compiled.recalled_count == 2
        assert len(compiled.validation_report.issues) >= 1
        assert any(
            i.issue == "stale" for i in compiled.validation_report.issues
        )

    @pytest.mark.asyncio
    async def test_compiled_context_to_dict(self):
        governor = self._make_governor(memories=[])
        compiled = await governor.compile(
            user_message="hello",
            system_prompt="assistant",
        )
        d = compiled.to_dict()
        assert "messages_count" in d
        assert "assembly" in d
        assert "quality" in d
        assert "validation" in d
        assert "authorization" in d

    @pytest.mark.asyncio
    async def test_empty_query_skips_recall(self):
        memories = [FakeMemory(content="should not be recalled")]
        governor = self._make_governor(memories=memories)
        compiled = await governor.compile(
            user_message="hello",
            query="",
        )
        assert compiled.recalled_count == 0

    @pytest.mark.asyncio
    async def test_governance_disabled_passes_all(self):
        now = time.time()
        memories = [
            FakeMemory(
                content="private data from other tenant",
                metadata={
                    "visibility": "private",
                    "tenant_id": "t2",
                    "user_id": "u2",
                    "timestamp": now,
                },
            ),
        ]
        governor = self._make_governor(memories=memories, with_governance=False)
        compiled = await governor.compile(
            query="private data",
            user_message="show me data",
            tenant_id="t1",
            user_id="u1",
        )
        assert compiled.recalled_count == 1
        assert compiled.authorization_report.allowed_count == 1
        assert len(compiled.validation_report.issues) == 0
