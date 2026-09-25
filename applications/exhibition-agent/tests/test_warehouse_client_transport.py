"""warehouse_client 传输层异常映射 + 重试测试（v1.2 直接 REST，#2 回归）。"""

from __future__ import annotations

import httpx
import pytest

from exhibition_agent.client.contract_errors import RateLimitedError, UpstreamError
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
            "venue": "保利世贸博览馆",
            "data_readiness": {"level": "complete"},
        },
    )


async def test_timeout_mapped_to_upstream_error():
    """httpx.TimeoutException → UpstreamError（不污染 trace 错误码分桶）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("simulated timeout")

    client = _make_client(httpx.MockTransport(handler), max_retries=0)
    with pytest.raises(UpstreamError) as exc:
        await client.get_rest(
            "/api/venue-schedule",
            params={"venue_id": "vn-001"},
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
        await client.get_rest(
            "/api/venue-schedule",
            params={"venue_id": "vn-001"},
            execution_context_header="dummy",
            request_id="req-001",
        )
    assert exc.value.code == ErrorCode.UPSTREAM_ERROR
    assert "ConnectError" in exc.value.message


async def test_upstream_error_retried_then_succeeds():
    """前两次 ConnectError，第三次成功 → 重试后返回 REST JSON。"""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise httpx.ConnectError("simulated connect error")
        return _success_response()

    client = _make_client(httpx.MockTransport(handler), max_retries=3, retry_base_delay_ms=0)
    data = await client.get_rest(
        "/api/venue-schedule",
        params={"venue_id": "vn-001"},
        execution_context_header="dummy",
        request_id="req-001",
    )
    assert call_count == 3
    assert data["venue"] == "保利世贸博览馆"


async def test_upstream_error_retry_exhausted():
    """始终 ConnectError，max_retries=2 → 调用 3 次（1+2）后抛 UpstreamError。"""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("simulated connect error")

    client = _make_client(httpx.MockTransport(handler), max_retries=2, retry_base_delay_ms=0)
    with pytest.raises(UpstreamError):
        await client.get_rest(
            "/api/venue-schedule",
            params={"venue_id": "vn-001"},
            execution_context_header="dummy",
            request_id="req-001",
        )
    assert call_count == 3


# ---------------------------------------------------------------------------
# Retry-After 解析 / 单次封顶 / 总预算（审核 N3 + W2）
# ---------------------------------------------------------------------------
async def test_retry_after_parsed_and_capped(monkeypatch):
    """429 + Retry-After: 300 → 解析生效但单次等待封顶 _MAX_RETRY_DELAY_MS（5s）。

    上游 Retry-After: 300（300s）× max_retries=2 不得把单请求拖挂 15 分钟。
    """
    from exhibition_agent.client import warehouse_client as wc

    delays: list[float] = []
    orig_sleep = wc.asyncio.sleep

    async def _record_sleep(seconds: float) -> None:
        delays.append(seconds)
        await orig_sleep(0)

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return httpx.Response(
                429,
                headers={"Retry-After": "300"},
                json={"error": {"code": "RATE_LIMITED", "message": "限流"}},
            )
        return _success_response()

    monkeypatch.setattr(wc.asyncio, "sleep", _record_sleep)
    client = _make_client(httpx.MockTransport(handler), max_retries=2, retry_base_delay_ms=0)
    data = await client.get_rest(
        "/api/venue-schedule",
        params={"venue_id": "vn-001"},
        execution_context_header="dummy",
        request_id="req-001",
    )

    assert call_count == 3
    assert data["venue"] == "保利世贸博览馆"
    assert len(delays) == 2
    assert all(d <= wc._MAX_RETRY_DELAY_MS / 1000 for d in delays), (
        f"重试等待超封顶上限：{delays}"
    )


async def test_retry_budget_exhausted_stops_retrying():
    """重试总预算耗尽 → 立即抛出，不再消耗下一次调用（N3 总 deadline）。"""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            429,
            headers={"Retry-After": "300"},
            json={"error": {"code": "RATE_LIMITED", "message": "限流"}},
        )

    client = WarehouseClient(
        base_url="http://mock-warehouse",
        transport=httpx.MockTransport(handler),
        timeout=5.0,
        max_retries=3,
        retry_base_delay_ms=0,
        retry_budget_ms=1,
    )
    with pytest.raises(RateLimitedError):
        await client.get_rest(
            "/api/venue-schedule",
            params={"venue_id": "vn-001"},
            execution_context_header="dummy",
            request_id="req-001",
        )
    assert call_count == 1, "重试总预算耗尽后不得再发起下一次调用"


async def test_retry_after_http_date_ignored_falls_back_to_backoff():
    """Retry-After 为 HTTP-date 形式 → 解析失败忽略（retry_after_ms=None），回落指数退避。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"},
            json={"error": {"code": "RATE_LIMITED", "message": "限流"}},
        )

    client = _make_client(httpx.MockTransport(handler), max_retries=0)
    with pytest.raises(RateLimitedError) as exc:
        await client.get_rest(
            "/api/venue-schedule",
            params={"venue_id": "vn-001"},
            execution_context_header="dummy",
            request_id="req-001",
        )
    assert exc.value.retry_after_ms is None, "HTTP-date 形式应忽略（仅解析秒数）"
