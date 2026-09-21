"""C2' 契约客户端（v1.2：直接 REST）：经 HTTP 调用 warehouse REST 端点。

只走 HTTP，不直连 MySQL（INV-6）。
v1.2 不再走 POST /api/v1/skills/{name} + 信封；直接调 warehouse REST 端点（GET /api/venue-schedule 等）。
返回 REST JSON dict；按 HTTP 状态码映射异常（401/403/404/422/429/502）。
保留：重试 / 超时 / traceparent 注入 / ExecutionContext 透传 / 重试总预算 / Retry-After 解析。
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Any, NoReturn

import httpx
from agent_core.logging import get_logger

from exhibition_agent.client.contract_errors import (
    AuthError,
    ContractError,
    DataNotConnectedError,
    EgressDeniedError,
    KnowledgeNotPublishedError,
    MetricPendingError,
    RateLimitedError,
    ScopeDeniedError,
    UpstreamError,
)
from exhibition_agent.contract.error_codes import (
    ErrorCode,
)
from exhibition_agent.observability.otel import inject_traceparent, span

logger = get_logger(__name__)

_CONTRACT_VERSION = "1.2"

_MAX_RETRY_DELAY_MS = 5_000
_RETRY_TOTAL_BUDGET_MS = 20_000

_UPSTREAM_SNIPPET_LIMIT = 200


def _map_http_error(status_code: int, payload: dict[str, Any] | None, text: str) -> ContractError:
    """按 HTTP 状态码 + body 映射为客户端异常（v1.2：不再走信封 error.code）。

    422 优先按 body.error / body.code 区分 MetricPending / DataNotConnected；
    其余按状态码映射。
    """
    body_error: str | None = None
    body_message: str = text[:_UPSTREAM_SNIPPET_LIMIT]
    if payload is not None:
        err = payload.get("error") if isinstance(payload.get("error"), dict) else None
        if err is not None:
            body_error = err.get("code")
            body_message = err.get("message", body_message)
        else:
            body_error = payload.get("code") or payload.get("error_code")

    if status_code == 401:
        code = ErrorCode.AUTH_CONTEXT_INVALID if body_error == "AUTH_CONTEXT_INVALID" else ErrorCode.AUTH_CONTEXT_MISSING
        return AuthError(code, body_message)
    if status_code == 403:
        if body_error == "EGRESS_DENIED":
            return EgressDeniedError(body_message)
        return ScopeDeniedError(body_message)
    if status_code == 404:
        return KnowledgeNotPublishedError(body_message)
    if status_code == 422:
        if body_error == "DATA_NOT_CONNECTED":
            return DataNotConnectedError(body_message)
        if body_error == "METRIC_BLOCKED":
            return MetricPendingError(ErrorCode.METRIC_BLOCKED, body_message)
        return MetricPendingError(ErrorCode.METRIC_NOT_VERIFIED, body_message)
    if status_code == 429:
        return RateLimitedError(body_message)
    if status_code == 502:
        return UpstreamError(body_message)
    return ContractError(ErrorCode.INTERNAL, body_message, status_code)


class WarehouseClient:
    """warehouse REST 客户端（httpx 异步，v1.2 直接 REST）。"""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 10.0,
        contract_version: str = _CONTRACT_VERSION,
        transport: httpx.AsyncBaseTransport | None = None,
        max_retries: int = 3,
        retry_base_delay_ms: int = 100,
        retry_budget_ms: int = _RETRY_TOTAL_BUDGET_MS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.contract_version = contract_version
        self.transport = transport
        self.max_retries = max_retries
        self.retry_base_delay_ms = retry_base_delay_ms
        self.retry_budget_ms = retry_budget_ms

    async def get_rest(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        execution_context_header: str,
        request_id: str,
        context_mode: str = "jwt",
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """GET warehouse REST 端点，返回 JSON dict。

        参数：
            path: 端点路径，如 /api/venue-schedule
            params: 查询参数
            execution_context_header / request_id / context_mode / extra_headers: 同 v1.1
        """
        return await self._request(
            "GET",
            path,
            execution_context_header=execution_context_header,
            request_id=request_id,
            context_mode=context_mode,
            extra_headers=extra_headers,
            params=params,
        )

    async def post_rest(
        self,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        execution_context_header: str,
        request_id: str,
        context_mode: str = "jwt",
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """POST warehouse REST 端点，返回 JSON dict。"""
        return await self._request(
            "POST",
            path,
            execution_context_header=execution_context_header,
            request_id=request_id,
            context_mode=context_mode,
            extra_headers=extra_headers,
            json_body=body,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        execution_context_header: str,
        request_id: str,
        context_mode: str = "jwt",
        extra_headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """统一请求入口（含重试 / traceparent / 传输层异常映射）。"""
        retry_deadline = time.monotonic() + self.retry_budget_ms / 1000
        headers = {
            "X-Execution-Context": execution_context_header,
            "X-Contract-Version": self.contract_version,
            "X-Context-Mode": context_mode,
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)

        for attempt in range(self.max_retries + 1):
            try:
                return await self._do_request(
                    method,
                    path,
                    headers,
                    request_id,
                    attempt=attempt,
                    params=params,
                    json_body=json_body,
                )
            except (UpstreamError, RateLimitedError) as exc:
                if attempt >= self.max_retries:
                    raise
                if isinstance(exc, RateLimitedError) and exc.retry_after_ms is not None:
                    delay_ms = float(exc.retry_after_ms)
                else:
                    delay_ms = self.retry_base_delay_ms * (2**attempt)
                    delay_ms += random.uniform(0, delay_ms * 0.1)
                delay_ms = min(delay_ms, _MAX_RETRY_DELAY_MS)
                if time.monotonic() + delay_ms / 1000 > retry_deadline:
                    logger.warning(
                        "warehouse 重试总预算耗尽（%.0fms），停止重试：%s",
                        self.retry_budget_ms,
                        exc,
                    )
                    raise
                logger.warning(
                    "warehouse 调用失败（attempt=%d/%d），%.0fms 后重试：%s",
                    attempt + 1,
                    self.max_retries + 1,
                    delay_ms,
                    exc,
                )
                await asyncio.sleep(delay_ms / 1000)
        raise RuntimeError("unreachable")

    async def _do_request(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        request_id: str,
        *,
        attempt: int = 0,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """单次调用：发请求 + 解析响应。传输层异常映射为 UpstreamError。"""
        with span(
            "exhibition_agent.warehouse_call",
            request_id=request_id,
            method=method,
            path=path,
            attempt=attempt if attempt > 0 else None,
        ):
            inject_traceparent(headers)
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout, transport=self.transport, base_url=self.base_url
                ) as client:
                    if method == "GET":
                        resp = await client.get(path, headers=headers, params=params)
                    else:
                        resp = await client.post(path, headers=headers, json=json_body)
            except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
                raise UpstreamError(f"warehouse 传输层故障：{type(exc).__name__}: {exc}") from exc

        return self._parse_rest_response(resp, request_id)

    def _parse_rest_response(self, resp: httpx.Response, request_id: str) -> dict[str, Any]:
        """解析 REST 响应：2xx 返回 JSON dict；4xx/5xx 按状态码映射异常。"""
        if 200 <= resp.status_code < 300:
            try:
                return resp.json()
            except ValueError as exc:
                raise ContractError(
                    ErrorCode.INTERNAL,
                    f"REST 成功响应非 JSON：{exc}",
                    500,
                ) from exc
        return self._parse_error(resp, request_id)

    def _parse_error(self, resp: httpx.Response, request_id: str) -> NoReturn:
        """错误响应解析：按 HTTP 状态码 + body 映射为客户端异常。"""
        payload: dict[str, Any] | None = None
        try:
            payload = resp.json()
        except ValueError:
            payload = None

        exc = _map_http_error(resp.status_code, payload, resp.text)
        if isinstance(exc, RateLimitedError):
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                try:
                    exc.retry_after_ms = int(float(retry_after) * 1000)
                except (ValueError, TypeError):
                    pass
        raise exc
