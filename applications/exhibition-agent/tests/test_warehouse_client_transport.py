"""warehouse_client 传输层异常映射 + 重试测试（#2 回归）。"""

from __future__ import annotations

import httpx
import pytest

from exhibition_agent.client.contract_errors import UpstreamError
from exhibition_agent.client.warehouse_client import WarehouseClient
from exhibition_agent.contract.error_codes import ErrorCode


def _make_client(transport: httpx.MockTransport, *, max_retries: int = 3, retry_base_delay_ms: int = 0) -> WarehouseClient:
    return WarehouseClient(
        base_url="http://mock-warehouse",
        transport=transport,
        timeout=5.0,
        max_retries=max_retries,
        retry_base_delay_ms=retry_base_delay_ms,
    )


def _success_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "request_id": "req-001",
            "data": {},
            "readiness": "READY",
            "classification": "INTERNAL",
            "sources": [],
            "citations": [],
            "warnings": [],
        },
    )


async def test_timeout_mapped_to_upstream_error():
    """httpx.TimeoutException → UpstreamError（不污染 trace 错误码分桶）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("simulated timeout")

    client = _make_client(httpx.MockTransport(handler), max_retries=0)
    with pytest.raises(UpstreamError) as exc:
        await client.invoke(
            "venue.schedule.query",
            {},
            execution_context_header="dummy",
            request_id="req-001",
        )
    assert exc.value.code == ErrorCode.UPSTREAM_ERROR
    assert "TimeoutException" in exc.value.message


async def test_connect_error_mapped_to_upstream_error():
    """httpx.ConnectError → UpstreamError。"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated connect error")

    client = _make_client(httpx.MockTransport(handler), max_retries=0)
    with pytest.raises(UpstreamError) as exc:
        await client.invoke(
            "venue.schedule.query",
            {},
            execution_context_header="dummy",
            request_id="req-001",
        )
    assert exc.value.code == ErrorCode.UPSTREAM_ERROR
    assert "ConnectError" in exc.value.message


async def test_upstream_error_retried_then_succeeds():
    """前两次 ConnectError，第三次成功 → 重试后返回信封。"""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise httpx.ConnectError("simulated connect error")
        return _success_response()

    client = _make_client(httpx.MockTransport(handler), max_retries=3, retry_base_delay_ms=0)
    envelope = await client.invoke(
        "venue.schedule.query",
        {},
        execution_context_header="dummy",
        request_id="req-001",
    )
    assert call_count == 3
    assert envelope.request_id == "req-001"


async def test_upstream_error_retry_exhausted():
    """始终 ConnectError，max_retries=2 → 调用 3 次（1+2）后抛 UpstreamError。"""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("simulated connect error")

    client = _make_client(httpx.MockTransport(handler), max_retries=2, retry_base_delay_ms=0)
    with pytest.raises(UpstreamError):
        await client.invoke(
            "venue.schedule.query",
            {},
            execution_context_header="dummy",
            request_id="req-001",
        )
    assert call_count == 3
