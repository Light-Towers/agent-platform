"""C2 契约客户端测试（统一信封 + 错误码映射 + 缺 readiness 判 fail + citations 强校验）。"""

from __future__ import annotations

import pytest

from exhibition_agent.client.contract_errors import (
    DataNotConnectedError,
    GroundednessError,
    KnowledgeNotPublishedError,
    MetricPendingError,
    ReadinessMissingError,
    ScopeDeniedError,
)
from exhibition_agent.contract.envelope import Readiness
from exhibition_agent.contract.error_codes import ErrorCode
from exhibition_agent.testing_helpers import ctx, ctx_header


@pytest.mark.parametrize("scenario,exc_type,code", [
    ("scope_denied", ScopeDeniedError, ErrorCode.SCOPE_DENIED),
    ("knowledge_not_published", KnowledgeNotPublishedError, ErrorCode.KNOWLEDGE_NOT_PUBLISHED),
    ("metric_not_verified", MetricPendingError, ErrorCode.METRIC_NOT_VERIFIED),
    ("metric_blocked", MetricPendingError, ErrorCode.METRIC_BLOCKED),
    ("data_not_connected", DataNotConnectedError, ErrorCode.DATA_NOT_CONNECTED),
])
async def test_error_code_mapping(
    warehouse_client, scenario, exc_type, code
):
    context = ctx()
    header = ctx_header(context)
    with pytest.raises(exc_type) as exc:
        await warehouse_client.invoke(
            "venue.schedule.query",
            {"exhibition_id": "ex-001"},
            execution_context_header=header,
            request_id=context.request_id,
            extra_headers={"X-Mock-Scenario": scenario},
        )
    assert exc.value.code == code


async def test_normal_success_envelope(warehouse_client):
    context = ctx()
    header = ctx_header(context)
    envelope = await warehouse_client.invoke(
        "venue.schedule.query",
        {"exhibition_id": "ex-001"},
        execution_context_header=header,
        request_id=context.request_id,
        extra_headers={"X-Mock-Scenario": "normal_200"},
    )
    assert envelope.readiness == Readiness.READY
    assert envelope.classification.value == "INTERNAL"
    assert len(envelope.sources) >= 1
    assert len(envelope.citations) >= 1


async def test_missing_readiness_fails(warehouse_client):
    """缺 readiness 的数值响应 → 判 fail（不是 warn）。"""
    context = ctx()
    header = ctx_header(context)
    with pytest.raises(ReadinessMissingError):
        await warehouse_client.invoke(
            "venue.schedule.query",
            {"exhibition_id": "ex-001"},
            execution_context_header=header,
            request_id=context.request_id,
            extra_headers={"X-Mock-Scenario": "missing_readiness"},
        )


async def test_knowledge_missing_citations_groundedness(warehouse_client):
    """知识类响应（sources 含 type=knowledge）缺 citations → 拒绝展示（groundedness，v1.1 §C2）。"""
    context = ctx()
    header = ctx_header(context)
    with pytest.raises(GroundednessError) as exc:
        await warehouse_client.invoke(
            "venue.schedule.query",
            {"exhibition_id": "ex-001"},
            execution_context_header=header,
            request_id=context.request_id,
            extra_headers={"X-Mock-Scenario": "knowledge_missing_citations"},
        )
    assert "citations" in exc.value.message
