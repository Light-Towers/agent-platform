"""warehouse REST 客户端测试（v1.2：直接 REST + HTTP 状态码映射 + data_readiness 自检）。"""

from __future__ import annotations

import pytest

from exhibition_agent.client.contract_errors import (
    DataNotConnectedError,
    KnowledgeNotPublishedError,
    MetricPendingError,
    ScopeDeniedError,
)
from exhibition_agent.contract.error_codes import ErrorCode
from exhibition_agent.testing_helpers import ctx, ctx_header


@pytest.mark.parametrize("scenario,exc_type,code", [
    ("scope_denied", ScopeDeniedError, ErrorCode.SCOPE_DENIED),
    ("knowledge_not_published", KnowledgeNotPublishedError, ErrorCode.KNOWLEDGE_NOT_PUBLISHED),
    ("metric_not_verified", MetricPendingError, ErrorCode.METRIC_NOT_VERIFIED),
    ("metric_blocked", MetricPendingError, ErrorCode.METRIC_BLOCKED),
    ("data_not_connected_422", DataNotConnectedError, ErrorCode.DATA_NOT_CONNECTED),
])
async def test_http_error_code_mapping(
    warehouse_client, scenario, exc_type, code
):
    """4xx 错误响应 → 按 HTTP 状态码 + body.error.code 映射为客户端异常。"""
    context = ctx()
    header = ctx_header(context)
    with pytest.raises(exc_type) as exc:
        await warehouse_client.get_rest(
            "/api/venue-schedule",
            params={"venue_id": "vn-001"},
            execution_context_header=header,
            request_id=context.request_id,
            extra_headers={"X-Mock-Scenario": scenario},
        )
    assert exc.value.code == code


async def test_normal_success_rest_returns_json_dict(warehouse_client):
    """200 正常响应 → 返回 REST JSON dict（不再解析信封）。"""
    context = ctx()
    header = ctx_header(context)
    data = await warehouse_client.get_rest(
        "/api/venue-schedule",
        params={"venue_id": "vn-001"},
        execution_context_header=header,
        request_id=context.request_id,
        extra_headers={"X-Mock-Scenario": "normal_200"},
    )
    assert isinstance(data, dict)
    assert data["venue"] == "保利世贸博览馆"
    assert data["data_readiness"]["level"] == "complete"
    assert len(data["citations"]) >= 1


async def test_data_not_connected_200_returns_pending_readiness(warehouse_client):
    """200 + data_readiness.level=pending → 返回 dict（skill 层自检 INV-10，不抛异常）。"""
    context = ctx()
    header = ctx_header(context)
    data = await warehouse_client.get_rest(
        "/api/venue-schedule",
        params={"venue_id": "vn-001"},
        execution_context_header=header,
        request_id=context.request_id,
        extra_headers={"X-Mock-Scenario": "data_not_connected"},
    )
    assert isinstance(data, dict)
    assert data["data_readiness"]["level"] == "pending"


async def test_missing_readiness_defaults_to_complete(warehouse_client):
    """200 + 无 data_readiness 字段 → 返回 dict（skill 层默认 READY，不再判 fail）。"""
    context = ctx()
    header = ctx_header(context)
    data = await warehouse_client.get_rest(
        "/api/venue-schedule",
        params={"venue_id": "vn-001"},
        execution_context_header=header,
        request_id=context.request_id,
        extra_headers={"X-Mock-Scenario": "missing_readiness"},
    )
    assert isinstance(data, dict)
    assert "data_readiness" not in data or not data.get("data_readiness")
    assert data["venue"] == "保利世贸博览馆"
