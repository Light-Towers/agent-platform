"""data_analysis.query：数据分析 Agent skill（只读）。

链路：NL → Metric Registry 校验（INV-10）→ HTTP 调 nl2sql-service → 返回结果。

INV-10 落地点：指标 status 非 VERIFIED → 答"该指标待接入"，不触 L3 text2sql、不生成 SQL。
  - BLOCKED          → METRIC_BLOCKED
  - status is None   → DATA_NOT_CONNECTED（metric 未登记）
  - 其他非 VERIFIED   → METRIC_NOT_VERIFIED（含 CONNECTED/CANDIDATE/REGISTERED/DEPRECATED）

nl2sql-service 通用化已完成（元知识参数化 + 命名去课程化），本 skill 经 HTTP
调 nl2sql-service /api/query 端点，按 SqlQueryResponse 契约组装 SkillResult。
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from agent_core.logging import get_logger

from exhibition_agent.contract.envelope import (
    DataClassification,
    Readiness,
    Source,
)
from exhibition_agent.contract.error_codes import PENDING_ANSWER
from exhibition_agent.foundation import metric_registry
from exhibition_agent.skills.base_skill import BaseSkill, SkillContext, SkillResult

logger = get_logger(__name__)

_NL2SQL_SERVICE_URL = os.environ.get("NL2SQL_SERVICE_URL", "http://localhost:8000")
_NL2SQL_ENDPOINT = "/api/query"
_NL2SQL_TIMEOUT_S = 30.0

_VERIFIED_STATUS = "VERIFIED"


def _map_non_verified_to_code(status: str | None) -> str:
    """非 VERIFIED status → INV-10 错误码。"""
    if status is None:
        return "DATA_NOT_CONNECTED"
    if status == "BLOCKED":
        return "METRIC_BLOCKED"
    return "METRIC_NOT_VERIFIED"


def _pending_result(code: str, metric_id: str, status: str | None) -> SkillResult:
    """INV-10 确定性结果：答'待接入'，不触 L3、不生成 SQL。"""
    return SkillResult(
        answer=PENDING_ANSWER,
        readiness=Readiness.NOT_CONNECTED,
        classification=DataClassification.INTERNAL,
        warnings=[f"{code}: metric_id={metric_id} status={status}"],
        error_code=code,
        data={"metric_id": metric_id, "metric_status": status},
    )


class DataAnalysisQuerySkill(BaseSkill):
    """数据分析 Agent skill（只读）。

    NL → Metric Registry 校验 → HTTP 调 nl2sql-service → 返回结果。
    非 VERIFIED 指标不得执行（INV-10），答"该指标待接入"，不生成 SQL。
    """

    name = "data_analysis.query"
    description = "自然语言问数 → Metric Registry 校验 → HTTP 调 nl2sql-service → 返回结果（只读）"

    async def run(self, params: dict[str, Any], ctx: SkillContext) -> SkillResult:
        metric_id = params.get("metric_id")
        nl_query = params.get("nl_query") or params.get("query")

        if not metric_id:
            return SkillResult(
                answer="缺少 metric_id，无法校验指标口径",
                readiness=Readiness.NOT_CONNECTED,
                classification=DataClassification.INTERNAL,
                error_code="METRIC_NOT_VERIFIED",
                data={"reason": "missing metric_id"},
            )

        status = metric_registry.get_metric_status(metric_id)
        if status != _VERIFIED_STATUS:
            code = _map_non_verified_to_code(status)
            logger.warning(
                "INV-10 命中：skill=%s metric_id=%s status=%s → 答'%s'，不触 L3、不生成 SQL",
                self.name,
                metric_id,
                status,
                PENDING_ANSWER,
            )
            return _pending_result(code, metric_id, status)

        return await self._call_nl2sql_service(metric_id, nl_query, ctx)

    async def _call_nl2sql_service(
        self,
        metric_id: str,
        nl_query: str | None,
        ctx: SkillContext,
    ) -> SkillResult:
        """HTTP 调 nl2sql-service /api/query，按 SqlQueryResponse 契约组装 SkillResult。

        nl2sql-service 返回 {"answer", "sql", "error", "data", "latency_ms", "fallback"}；
        error 非空时标记 NOT_CONNECTED，否则 READY。
        """
        url = f"{_NL2SQL_SERVICE_URL}{_NL2SQL_ENDPOINT}"
        payload: dict[str, Any] = {"query": nl_query or ""}
        if metric_id:
            payload["metric_id"] = metric_id

        try:
            async with httpx.AsyncClient(timeout=_NL2SQL_TIMEOUT_S) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                result = resp.json()
        except httpx.TimeoutException:
            logger.warning("nl2sql-service 超时: metric_id=%s url=%s", metric_id, url)
            return SkillResult(
                answer="数据查询超时，请稍后重试",
                readiness=Readiness.NOT_CONNECTED,
                classification=DataClassification.INTERNAL,
                error_code="UPSTREAM_TIMEOUT",
                data={"metric_id": metric_id, "nl_query": nl_query},
            )
        except Exception as exc:
            logger.warning("nl2sql-service 调用失败: metric_id=%s error=%s", metric_id, exc)
            return SkillResult(
                answer="数据查询服务暂时不可用",
                readiness=Readiness.NOT_CONNECTED,
                classification=DataClassification.INTERNAL,
                error_code="UPSTREAM_ERROR",
                data={"metric_id": metric_id, "nl_query": nl_query},
            )

        answer = result.get("answer", "")
        sql = result.get("sql")
        error = result.get("error")
        latency_ms = result.get("latency_ms")
        fallback = result.get("fallback", False)

        if error:
            logger.warning("nl2sql-service 返回错误: metric_id=%s error=%s", metric_id, error)
            return SkillResult(
                answer=answer or "数据查询失败",
                readiness=Readiness.NOT_CONNECTED,
                classification=DataClassification.INTERNAL,
                error_code="NL2SQL_ERROR",
                sources=[Source(type="api", name="nl2sql-service")],
                data={"metric_id": metric_id, "sql": sql, "error": error},
            )

        return SkillResult(
            answer=answer,
            readiness=Readiness.READY,
            classification=DataClassification.INTERNAL,
            sources=[Source(type="api", name="nl2sql-service")],
            data={
                "metric_id": metric_id,
                "nl_query": nl_query,
                "sql": sql,
                "latency_ms": latency_ms,
                "fallback": fallback,
            },
        )
