"""data_analysis.query：数据分析 Agent skill（P1 骨架，只读）。

链路：NL → Metric Registry 校验（INV-10）→ HTTP 调 nl2sql-service（端点 TODO）→ 返回结果。

INV-10 落地点：指标 status 非 VERIFIED → 答"该指标待接入"，不触 L3 text2sql、不生成 SQL。
  - BLOCKED          → METRIC_BLOCKED
  - status is None   → DATA_NOT_CONNECTED（metric 未登记）
  - 其他非 VERIFIED   → METRIC_NOT_VERIFIED（含 CONNECTED/CANDIDATE/REGISTERED/DEPRECATED）

nl2sql-service 通用化（nl2sql-service 12 节点 LangGraph 通用服务）是后续步骤；
当前 skill 结构完整，HTTP 端点标 TODO，VERIFIED 分支返回确定性骨架结果。
"""

from __future__ import annotations

from typing import Any

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

# nl2sql-service 端点（TODO：nl2sql-service 通用化后填充实际端点）。
# 骨架阶段为常量，VERIFIED 分支不实际发起 HTTP，返回确定性 stub 结果。
_NL2SQL_ENDPOINT: str = "TODO: /api/nl2sql/query (nl2sql-service 通用化后填充)"

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
    """数据分析 Agent skill（P1 骨架，只读）。

    NL → Metric Registry 校验 → HTTP 调 nl2sql-service → 返回结果。
    非 VERIFIED 指标不得执行（INV-10），答"该指标待接入"，不生成 SQL。
    """

    name = "data_analysis.query"
    description = "自然语言问数 → Metric Registry 校验 → HTTP 调 nl2sql-service → 返回结果（只读骨架）"

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
        """HTTP 调 nl2sql-service（骨架：端点 TODO，返回确定性 stub 结果）。

        TODO: nl2sql-service 通用化后，通过 ctx.warehouse_client.get_rest(
            _NL2SQL_ENDPOINT,
            params={"query": nl_query, "metric_id": metric_id},
            execution_context_header=ctx.execution_context_header,
            request_id=ctx.execution_context.request_id,
            context_mode=ctx.context_mode,
            extra_headers=ctx.extra_headers,
        ) 发起实际 HTTP 调用，并按 nl2sql-service SqlQueryResponse 契约
        （answer / sql / error / fallback / latency_ms）自组装 SkillResult。
        当前骨架阶段不发起 HTTP，返回确定性 stub 结果以贯通 VERIFIED 路径。
        """
        logger.info(
            "data_analysis 骨架：metric_id=%s 已 VERIFIED，nl2sql 端点待接入（%s）",
            metric_id,
            _NL2SQL_ENDPOINT,
        )
        return SkillResult(
            answer=f"指标 {metric_id} 已校验，问数结果待 nl2sql-service 接入",
            readiness=Readiness.READY,
            classification=DataClassification.INTERNAL,
            sources=[Source(type="api", name="nl2sql-service")],
            warnings=[f"骨架：nl2sql 端点待接入（{_NL2SQL_ENDPOINT}）"],
            data={
                "metric_id": metric_id,
                "nl_query": nl_query,
                "nl2sql_endpoint": _NL2SQL_ENDPOINT,
                "skeleton": True,
            },
        )
