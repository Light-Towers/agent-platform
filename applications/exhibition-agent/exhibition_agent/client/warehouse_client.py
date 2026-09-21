"""C2 契约客户端：经 HTTP 调用 warehouse 领域 API。

只走 HTTP，不直连 MySQL（INV-6）。统一信封解析 + 错误码映射 + 缺 readiness 判 fail。
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, NoReturn

import httpx
from agent_core.logging import get_logger

from exhibition_agent.client.contract_errors import (
    AuthError,
    ContractError,
    DataNotConnectedError,
    EgressDeniedError,
    GroundednessError,
    KnowledgeNotPublishedError,
    MetricPendingError,
    RateLimitedError,
    ReadinessMissingError,
    ScopeDeniedError,
    UpstreamError,
)
from exhibition_agent.contract.envelope import SkillSuccessEnvelope
from exhibition_agent.contract.error_codes import (
    ERROR_CODE_HTTP_MAP,
    METRIC_PENDING_CODES,
    ErrorCode,
)
from exhibition_agent.observability.otel import inject_traceparent, span

logger = get_logger(__name__)

_CONTRACT_VERSION = "1.1"


def _map_error_code(code_str: str, message: str) -> ContractError:
    """把 warehouse 返回的错误码映射为客户端异常。"""
    try:
        code = ErrorCode(code_str)
    except ValueError:
        return ContractError(ErrorCode.INTERNAL, f"未知错误码：{code_str} / {message}", 500)

    if code == ErrorCode.AUTH_CONTEXT_MISSING or code == ErrorCode.AUTH_CONTEXT_INVALID:
        return AuthError(code, message)
    if code == ErrorCode.SCOPE_DENIED:
        return ScopeDeniedError(message)
    if code == ErrorCode.EGRESS_DENIED:
        return EgressDeniedError(message)
    if code == ErrorCode.KNOWLEDGE_NOT_PUBLISHED:
        return KnowledgeNotPublishedError(message)
    if code in METRIC_PENDING_CODES:
        return MetricPendingError(code, message)
    if code == ErrorCode.DATA_NOT_CONNECTED:
        return DataNotConnectedError(message)
    if code == ErrorCode.RATE_LIMITED:
        return RateLimitedError(message)
    if code == ErrorCode.UPSTREAM_ERROR:
        return UpstreamError(message)
    return ContractError(code, message, ERROR_CODE_HTTP_MAP[code])


class WarehouseClient:
    """warehouse 契约客户端（httpx 异步）。"""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 10.0,
        contract_version: str = _CONTRACT_VERSION,
        transport: httpx.AsyncBaseTransport | None = None,
        max_retries: int = 3,
        retry_base_delay_ms: int = 100,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.contract_version = contract_version
        self.transport = transport
        self.max_retries = max_retries
        self.retry_base_delay_ms = retry_base_delay_ms

    async def invoke(
        self,
        skill: str,
        params: dict[str, Any],
        *,
        execution_context_header: str,
        request_id: str,
        context_mode: str = "jwt",
        options: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> SkillSuccessEnvelope:
        """调用 warehouse 的 skill 端点，解析统一信封。

        参数：
            skill: skill 名，如 venue.schedule.query
            params: skill 参数
            execution_context_header: X-Execution-Context 原始头值（透传，不重编码）
            request_id: 审计键（从 ExecutionContext 提取）
            context_mode: 上下文传递模式（jwt/base64），写入 X-Context-Mode 头供 warehouse 侧解析
            options: 可选选项（include_readiness / limit 等）
            extra_headers: 额外请求头（如测试用 X-Mock-Scenario 切换场景）

        返回：校验通过的 SkillSuccessEnvelope。

        raise：ContractError 子类（按错误码映射）；ReadinessMissingError（缺 readiness）。

        重试：对 UpstreamError（传输层故障/上游 502）与 RateLimitedError（429）做有界指数退避重试
        （max_retries 次，base * 2^attempt + 10% 抖动）。调用方需确保 skill 幂等；
        当前所有 skill 均为只读，重试安全。
        """
        url = f"/api/v1/skills/{skill}"
        headers = {
            "X-Execution-Context": execution_context_header,
            "X-Contract-Version": self.contract_version,
            "X-Context-Mode": context_mode,
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)
        body = {
            "request_id": request_id,
            "skill": skill,
            "params": params,
            "options": options or {},
        }

        for attempt in range(self.max_retries + 1):
            try:
                return await self._do_invoke(skill, url, headers, body, request_id, attempt=attempt)
            except (UpstreamError, RateLimitedError) as exc:
                if attempt >= self.max_retries:
                    raise
                # 优先尊重 warehouse 的 Retry-After 头（429）；否则指数退避 + 10% 抖动
                if isinstance(exc, RateLimitedError) and exc.retry_after_ms is not None:
                    delay_ms = float(exc.retry_after_ms)
                else:
                    delay_ms = self.retry_base_delay_ms * (2**attempt)
                    delay_ms += random.uniform(0, delay_ms * 0.1)
                logger.warning(
                    "warehouse 调用失败（attempt=%d/%d），%.0fms 后重试：%s",
                    attempt + 1,
                    self.max_retries + 1,
                    delay_ms,
                    exc,
                )
                await asyncio.sleep(delay_ms / 1000)
        raise RuntimeError("unreachable")

    async def _do_invoke(
        self,
        skill: str,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        request_id: str,
        *,
        attempt: int = 0,
    ) -> SkillSuccessEnvelope:
        """单次调用：发请求 + 解析响应。传输层异常映射为 UpstreamError。

        traceparent 在 warehouse_call span 内注入（W3C 传播）：warehouse 侧 span
        以 warehouse_call span 为 parent，trace 链完整；重试时每次 attempt 在
        各自 span 内重新注入，不携带陈旧 span context（OTel inject 为覆盖语义）。
        """
        with span(
            "exhibition_agent.warehouse_call",
            request_id=request_id,
            skill=skill,
            attempt=attempt if attempt > 0 else None,
        ):
            inject_traceparent(headers)
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout, transport=self.transport, base_url=self.base_url
                ) as client:
                    resp = await client.post(url, headers=headers, json=body)
            except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
                raise UpstreamError(f"warehouse 传输层故障：{type(exc).__name__}: {exc}") from exc

        return self._parse_response(resp, request_id)

    def _parse_response(self, resp: httpx.Response, request_id: str) -> SkillSuccessEnvelope:
        """解析统一信封：2xx 成功信封 / 4xx 5xx 错误信封。"""
        if 200 <= resp.status_code < 300:
            return self._parse_success(resp, request_id)
        return self._parse_error(resp, request_id)

    def _parse_success(self, resp: httpx.Response, request_id: str) -> SkillSuccessEnvelope:
        """成功信封解析：缺 readiness 数值响应 → 判 fail；知识类缺 citations → 拒绝展示。"""
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ReadinessMissingError(f"成功响应非 JSON：{exc}") from exc

        data = payload.get("data")
        has_numeric_data = isinstance(data, (dict, list)) and bool(data)
        if has_numeric_data and "readiness" not in payload:
            raise ReadinessMissingError("数值响应缺 readiness 字段，判 fail")

        try:
            envelope = SkillSuccessEnvelope.model_validate(payload)
        except Exception as exc:
            raise ReadinessMissingError(f"成功信封校验失败：{exc}") from exc

        self._check_groundedness(envelope)

        return envelope

    @staticmethod
    def _check_groundedness(envelope: SkillSuccessEnvelope) -> None:
        """知识类响应 groundedness 校验（契约 v1.1 §C2）。

        sources 含 type=="knowledge" 却无 citations → 拒绝展示（GroundednessError）。
        """
        has_knowledge_source = any(s.type == "knowledge" for s in envelope.sources)
        if has_knowledge_source and not envelope.citations:
            raise GroundednessError(
                "知识类响应（sources 含 type=knowledge）缺 citations，拒绝展示"
            )

    def _parse_error(self, resp: httpx.Response, request_id: str) -> NoReturn:
        """错误信封解析：按 error_code 映射为客户端异常。"""
        try:
            payload = resp.json()
            err = payload.get("error", {})
            code_str = err.get("code", "INTERNAL")
            message = err.get("message", resp.text)
        except ValueError:
            code_str = "INTERNAL"
            message = resp.text

        exc = _map_error_code(code_str, message)
        # 429 Retry-After 头提取（秒或 HTTP-date；仅解析秒数，date 形式忽略）
        if isinstance(exc, RateLimitedError):
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                try:
                    exc.retry_after_ms = int(float(retry_after) * 1000)
                except (ValueError, TypeError):
                    pass
        raise exc
