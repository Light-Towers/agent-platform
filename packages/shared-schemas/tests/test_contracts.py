"""shared-schemas 契约测试：字段约束 / 序列化往返 / 默认值 / 边界。"""

from __future__ import annotations

import pytest
from shared_schemas.health import DependencyHealth, HealthResponse, HealthStatus
from shared_schemas.intent import IntentCandidate, IntentResult
from shared_schemas.query import QueryData, QueryRequest, QueryResponse
from shared_schemas.subagent import SubagentCall, SubagentResult
from shared_schemas.thread import (
    THREAD_STATE_VERSION,
    ThreadState,
    empty_thread_state,
    message_dict,
)

# ---- QueryRequest ----


class TestQueryRequest:
    def test_required_query_field(self):
        with pytest.raises(Exception):
            QueryRequest()

    def test_defaults(self):
        r = QueryRequest(query="hello")
        assert r.query == "hello"
        assert r.tenant_id is None
        assert r.session_id is None
        assert r.context == {}
        assert r.priority is None
        assert r.user_id is None

    def test_full_construction(self):
        r = QueryRequest(
            query="q",
            tenant_id="t1",
            session_id="s1",
            context={"k": "v"},
            priority="high",
            user_id="u1",
        )
        assert r.tenant_id == "t1"
        assert r.priority == "high"

    def test_invalid_priority(self):
        with pytest.raises(Exception):
            QueryRequest(query="q", priority="invalid")

    def test_legacy_thread_id_alias(self):
        """旧契约字段 thread_id 应映射到 session_id（T1.8/C3 兼容）。"""
        r = QueryRequest.model_validate({"query": "q", "thread_id": "t-legacy"})
        assert r.session_id == "t-legacy"

    def test_session_id_still_accepted(self):
        """新字段名 session_id 正常工作（alias 不破坏现行为）。"""
        r = QueryRequest.model_validate({"query": "q", "session_id": "s-new"})
        assert r.session_id == "s-new"

    def test_alias_serialization_uses_session_id(self):
        """序列化输出用新字段名 session_id（不回吐旧名）。"""
        r = QueryRequest.model_validate({"query": "q", "thread_id": "t1"})
        d = r.model_dump(by_alias=True)
        assert "session_id" in d
        assert "thread_id" not in d

    def test_serialization_roundtrip(self):
        r = QueryRequest(query="q", tenant_id="t1", context={"a": 1})
        d = r.model_dump()
        r2 = QueryRequest.model_validate(d)
        assert r2 == r


# ---- QueryResponse / QueryData ----


class TestQueryResponse:
    def test_minimal(self):
        resp = QueryResponse(answer="ok")
        assert resp.answer == "ok"
        assert resp.data is None
        assert resp.latency_ms is None

    def test_with_data(self):
        data = QueryData(content={"rows": [1, 2]}, source="mysql", metadata={"cost": 0.1})
        resp = QueryResponse(answer="ok", data=data, latency_ms=12.5, intent="sql")
        assert resp.data.content == {"rows": [1, 2]}
        assert resp.data.source == "mysql"
        assert resp.latency_ms == 12.5

    def test_serialization_roundtrip(self):
        resp = QueryResponse(answer="ok", data=QueryData(content=[1, 2]))
        d = resp.model_dump()
        r2 = QueryResponse.model_validate(d)
        assert r2 == resp


# ---- ThreadState ----


class TestThreadState:
    def test_defaults(self):
        ts = ThreadState()
        assert ts.thread_id == ""
        assert ts.messages == []
        assert ts.metadata == {}
        assert ts.version == THREAD_STATE_VERSION

    def test_message_dict(self):
        m = message_dict("user", "hello", tool_calls=[])
        assert m["role"] == "user"
        assert m["content"] == "hello"
        assert m["tool_calls"] == []

    def test_empty_thread_state(self):
        ts = empty_thread_state("t1")
        assert ts.thread_id == "t1"
        assert ts.messages == []

    def test_serialization_roundtrip(self):
        ts = ThreadState(
            thread_id="t1",
            messages=[{"role": "user", "content": "hi"}],
            metadata={"route": "sql"},
        )
        d = ts.model_dump()
        ts2 = ThreadState.model_validate(d)
        assert ts2 == ts


# ---- Health ----


class TestHealth:
    def test_status_enum(self):
        assert HealthStatus.HEALTHY == "healthy"
        assert HealthStatus.DEGRADED == "degraded"
        assert HealthStatus.UNHEALTHY == "unhealthy"

    def test_dependency_health(self):
        dh = DependencyHealth(name="mysql", status=HealthStatus.HEALTHY, latency_ms=1.5)
        assert dh.detail is None

    def test_health_response_defaults(self):
        resp = HealthResponse(status=HealthStatus.HEALTHY, version="1.0")
        assert resp.dependencies == []
        assert resp.llm is False
        assert resp.mcp is False
        assert resp.storage is None

    def test_health_response_full(self):
        resp = HealthResponse(
            status=HealthStatus.DEGRADED,
            version="2.0",
            dependencies=[DependencyHealth(name="redis", status=HealthStatus.UNHEALTHY)],
            storage="postgres",
            llm=True,
            mcp=True,
        )
        assert resp.dependencies[0].name == "redis"
        assert resp.llm is True


# ---- Intent ----


class TestIntent:
    def test_candidate_confidence_bounds(self):
        IntentCandidate(intent="a", confidence=0.0)
        IntentCandidate(intent="a", confidence=1.0)
        with pytest.raises(Exception):
            IntentCandidate(intent="a", confidence=-0.1)
        with pytest.raises(Exception):
            IntentCandidate(intent="a", confidence=1.1)

    def test_intent_result_defaults(self):
        r = IntentResult(primary=IntentCandidate(intent="sql", confidence=0.9))
        assert r.candidates == []
        assert r.source == "l1"
        assert r.rewritten_query is None


# ---- Subagent ----


class TestSubagent:
    def test_call_defaults(self):
        c = SubagentCall(subagent_name="search")
        assert c.args == {}
        assert c.mode == "remote"

    def test_result_defaults(self):
        r = SubagentResult(subagent_name="search", result="ok")
        assert r.success is True
        assert r.fallback is False
        assert r.error is None
        assert r.latency_ms is None

    def test_result_error(self):
        r = SubagentResult(subagent_name="search", result="", success=False, error="timeout")
        assert r.success is False
        assert r.error == "timeout"


# ---- sse_pack ----


class TestSsePack:
    def test_no_event(self):
        from shared_schemas import sse_pack

        result = sse_pack("", {"type": "done"})
        assert result == 'data: {"type": "done"}\n\n'

    def test_with_event(self):
        from shared_schemas import sse_pack

        result = sse_pack("progress", {"step": 1})
        assert result == 'event: progress\ndata: {"step": 1}\n\n'

    def test_empty_data(self):
        from shared_schemas import sse_pack

        result = sse_pack("ready")
        assert result == 'event: ready\ndata: {}\n\n'

    def test_unicode(self):
        from shared_schemas import sse_pack

        result = sse_pack("", {"text": "中文"})
        assert "中文" in result
        assert "\n\n" in result
