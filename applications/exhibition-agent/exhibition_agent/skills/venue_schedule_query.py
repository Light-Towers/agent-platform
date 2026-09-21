"""venue.schedule.query：场馆档期查询（只读 skill）。

INV-10 落地点：收到 MetricPendingError / DataNotConnectedError → 答"该指标待接入"，
不触 L3 text2sql、不生成任何 SQL。
Groundedness：知识类缺 citations → 拒绝展示（契约 v1.1 §C2）。
"""

from __future__ import annotations

from typing import Any

from agent_core.logging import get_logger

from exhibition_agent.client.contract_errors import (
    ContractError,
    DataNotConnectedError,
    EgressDeniedError,
    GroundednessError,
    KnowledgeNotPublishedError,
    MetricPendingError,
    ReadinessMissingError,
    ScopeDeniedError,
)
from exhibition_agent.contract.envelope import DataClassification, EgressDecision, Readiness
from exhibition_agent.contract.error_codes import PENDING_ANSWER
from exhibition_agent.skills.base_skill import BaseSkill, SkillContext, SkillResult

logger = get_logger(__name__)


def _pending_result(code: str, message: str) -> SkillResult:
    """INV-10 确定性结果：答'待接入'，不触 L3、不生成 SQL。"""
    return SkillResult(
        answer=PENDING_ANSWER,
        readiness=Readiness.NOT_CONNECTED,
        classification=DataClassification.INTERNAL,
        warnings=[f"{code}: {message}"],
        error_code=code,
    )


class VenueScheduleQuerySkill(BaseSkill):
    """场馆档期查询（只读）。"""

    name = "venue.schedule.query"
    description = "查询场馆档期/排期信息（只读）"

    async def run(self, params: dict[str, Any], ctx: SkillContext) -> SkillResult:
        ec = ctx.execution_context
        try:
            envelope = await ctx.warehouse_client.invoke(
                self.name,
                params,
                execution_context_header=ctx.execution_context_header,
                request_id=ec.request_id,
                context_mode=ctx.context_mode,
                options={"include_readiness": True},
                extra_headers=ctx.extra_headers,
            )
        except MetricPendingError as exc:
            logger.warning(
                "INV-10 命中：skill=%s code=%s → 答'%s'，不触 L3、不生成 SQL",
                self.name,
                exc.code.value,
                PENDING_ANSWER,
            )
            return _pending_result(exc.code.value, exc.message)
        except DataNotConnectedError as exc:
            logger.warning(
                "INV-10 命中：skill=%s code=%s → 答'%s'，不触 L3、不生成 SQL",
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
        except GroundednessError as exc:
            logger.warning("groundedness fail: %s", exc.message)
            return SkillResult(
                answer="该回答缺乏引用支撑，拒绝展示",
                readiness=Readiness.NOT_CONNECTED,
                classification=DataClassification.INTERNAL,
                error_code=exc.code.value,
            )
        except ReadinessMissingError as exc:
            logger.error("readiness missing, fail: %s", exc.message)
            return SkillResult(
                answer="数据就绪度缺失，拒绝回答",
                readiness=Readiness.NOT_CONNECTED,
                classification=DataClassification.INTERNAL,
                error_code=exc.code.value,
                data={"readiness_missing": True},
            )
        except ContractError as exc:
            logger.error("contract error: %s", exc)
            raise

        return SkillResult(
            answer=self._format_answer(envelope.data, envelope.citations),
            readiness=envelope.readiness,
            classification=envelope.classification,
            sources=envelope.sources,
            citations=envelope.citations,
            warnings=envelope.warnings,
            retrieval_hit_ids=[c.knowledge_id for c in envelope.citations],
            data=envelope.data,
        )

    @staticmethod
    def _format_answer(data: dict[str, Any], citations: list[Any]) -> str:
        """组装回答（带 citation + readiness 提示）。"""
        lines: list[str] = []
        if data:
            for key, value in data.items():
                lines.append(f"{key}: {value}")
        else:
            lines.append("（无数据）")
        if citations:
            lines.append(f"\n引用：{len(citations)} 条")
        return "\n".join(lines)
