"""venue.schedule.query：场馆档期查询（只读 skill，v1.2 直接 REST）。

INV-10 落地点（双轨）：
1. warehouse REST 返回 422（METRIC_NOT_VERIFIED / METRIC_BLOCKED / DATA_NOT_CONNECTED）→ 异常 → 答"该指标待接入"
2. warehouse REST 返回 200 但 data_readiness.level in ("pending","sparse_sample","incomplete") → skill 层自检 → 答"该指标待接入"
两轨均不触 L3 text2sql、不生成任何 SQL。
"""

from __future__ import annotations

from typing import Any

from agent_core.logging import get_logger

from exhibition_agent.client.contract_errors import (
    ContractError,
    DataNotConnectedError,
    EgressDeniedError,
    KnowledgeNotPublishedError,
    MetricPendingError,
    ScopeDeniedError,
)
from exhibition_agent.contract.envelope import (
    Citation,
    DataClassification,
    EgressDecision,
    Readiness,
    Source,
)
from exhibition_agent.contract.error_codes import PENDING_ANSWER
from exhibition_agent.skills.base_skill import BaseSkill, SkillContext, SkillResult

logger = get_logger(__name__)

_REST_PATH = "/api/venue-schedule"
_SOURCE_TABLE = "t_venue_schedule"

_PENDING_LEVELS: frozenset[str] = frozenset({"pending", "sparse_sample", "incomplete"})


def _pending_result(code: str, message: str) -> SkillResult:
    """INV-10 确定性结果：答'待接入'，不触 L3、不生成 SQL。"""
    return SkillResult(
        answer=PENDING_ANSWER,
        readiness=Readiness.NOT_CONNECTED,
        classification=DataClassification.INTERNAL,
        warnings=[f"{code}: {message}"],
        error_code=code,
    )


def _map_readiness(level: str | None) -> Readiness:
    """warehouse REST data_readiness.level → 平台侧 Readiness 枚举。"""
    if level is None or level == "complete":
        return Readiness.READY
    if level in _PENDING_LEVELS:
        return Readiness.NOT_CONNECTED
    if level == "synthetic":
        return Readiness.SYNTHETIC
    if level == "partial":
        return Readiness.PARTIAL
    return Readiness.READY


class VenueScheduleQuerySkill(BaseSkill):
    """场馆档期查询（只读，v1.2 直接 REST）。"""

    name = "venue.schedule.query"
    description = "查询场馆档期/排期信息（只读，直接调 warehouse REST）"

    async def run(self, params: dict[str, Any], ctx: SkillContext) -> SkillResult:
        ec = ctx.execution_context
        query_params = self._build_query_params(params)
        try:
            data = await ctx.warehouse_client.get_rest(
                _REST_PATH,
                params=query_params,
                execution_context_header=ctx.execution_context_header,
                request_id=ec.request_id,
                context_mode=ctx.context_mode,
                extra_headers=ctx.extra_headers,
            )
        except MetricPendingError as exc:
            logger.warning(
                "INV-10 命中（422）：skill=%s code=%s → 答'%s'，不触 L3、不生成 SQL",
                self.name,
                exc.code.value,
                PENDING_ANSWER,
            )
            return _pending_result(exc.code.value, exc.message)
        except DataNotConnectedError as exc:
            logger.warning(
                "INV-10 命中（422）：skill=%s code=%s → 答'%s'，不触 L3、不生成 SQL",
                self.name,
                exc.code.value,
                PENDING_ANSWER,
            )
            return _pending_result(exc.code.value, exc.message)
        except ScopeDeniedError as exc:
            logger.warning("scope denied: %s", exc.message)
            return SkillResult(
                answer="无权访问该资源",
                readiness=Readiness.NOT_CONNECTED,
                classification=DataClassification.INTERNAL,
                error_code=exc.code.value,
            )
        except EgressDeniedError as exc:
            logger.warning("egress denied: %s", exc.message)
            return SkillResult(
                answer="数据出域策略未通过，拒绝回答",
                readiness=Readiness.NOT_CONNECTED,
                classification=DataClassification.CONFIDENTIAL,
                error_code=exc.code.value,
                egress_decision=EgressDecision.DENY,
            )
        except KnowledgeNotPublishedError as exc:
            logger.info("knowledge not published: %s", exc.message)
            return SkillResult(
                answer="该知识尚未发布",
                readiness=Readiness.NOT_CONNECTED,
                classification=DataClassification.INTERNAL,
                error_code=exc.code.value,
            )
        except ContractError as exc:
            logger.error("contract error: %s", exc)
            raise

        return self._assemble_result(data)

    @staticmethod
    def _build_query_params(params: dict[str, Any]) -> dict[str, Any]:
        """把 skill params 映射为 REST 查询参数。"""
        query: dict[str, Any] = {}
        if "venue_id" in params:
            query["venue_id"] = params["venue_id"]
        if "exhibition_id" in params:
            query["exhibition_id"] = params["exhibition_id"]
        return query

    def _assemble_result(self, data: dict[str, Any]) -> SkillResult:
        """从 REST JSON 自组装 SkillResult（v1.2：平台侧自组装，不再解析信封）。"""
        readiness_level = self._extract_readiness_level(data)
        readiness = _map_readiness(readiness_level)

        if readiness_level in _PENDING_LEVELS:
            logger.warning(
                "INV-10 命中（200 data_readiness）：skill=%s level=%s → 答'%s'，不触 L3、不生成 SQL",
                self.name,
                readiness_level,
                PENDING_ANSWER,
            )
            return SkillResult(
                answer=PENDING_ANSWER,
                readiness=Readiness.NOT_CONNECTED,
                classification=DataClassification.INTERNAL,
                warnings=[f"DATA_NOT_CONNECTED: data_readiness.level={readiness_level}"],
                error_code="DATA_NOT_CONNECTED",
                data=data,
            )

        citations = self._extract_citations(data)
        warnings: list[str] = []
        if readiness == Readiness.SYNTHETIC:
            warnings.append("合成数据，仅供链路演示，非真实经营结论")
        if readiness == Readiness.PARTIAL:
            warnings.append("部分数据为稀疏/样本，结论仅供参考")

        return SkillResult(
            answer=self._format_answer(data, citations),
            readiness=readiness,
            classification=DataClassification.INTERNAL,
            sources=[Source(type="table", name=_SOURCE_TABLE, as_of=data.get("as_of"))],
            citations=citations,
            warnings=warnings,
            retrieval_hit_ids=[c.knowledge_id for c in citations],
            data=data,
        )

    @staticmethod
    def _extract_readiness_level(data: dict[str, Any]) -> str | None:
        """从 REST JSON 提取 data_readiness.level（兼容嵌套与扁平）。"""
        dr = data.get("data_readiness")
        if isinstance(dr, dict):
            return dr.get("level")
        if isinstance(dr, str):
            return dr
        return data.get("readiness_level")

    @staticmethod
    def _extract_citations(data: dict[str, Any]) -> list[Citation]:
        """从 REST JSON 提取 citations（如有）。"""
        raw = data.get("citations")
        if not isinstance(raw, list):
            return []
        result: list[Citation] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            kid = item.get("knowledge_id") or item.get("id")
            if not kid:
                continue
            result.append(
                Citation(
                    knowledge_id=str(kid),
                    chunk_id=item.get("chunk_id"),
                    scope=item.get("scope"),
                )
            )
        return result

    @staticmethod
    def _format_answer(data: dict[str, Any], citations: list[Citation]) -> str:
        """组装回答（带 readiness 提示）。"""
        lines: list[str] = []
        venue = data.get("venue") or data.get("venue_name")
        exhibition = data.get("exhibition") or data.get("exhibition_name")
        date_range = data.get("date_range") or data.get("schedule")
        if venue:
            lines.append(f"场馆: {venue}")
        if exhibition:
            lines.append(f"展会: {exhibition}")
        if date_range:
            lines.append(f"档期: {date_range}")
        if not lines:
            if data:
                for key, value in list(data.items())[:8]:
                    lines.append(f"{key}: {value}")
            else:
                lines.append("（无数据）")
        if citations:
            lines.append(f"\n引用：{len(citations)} 条")
        return "\n".join(lines)
