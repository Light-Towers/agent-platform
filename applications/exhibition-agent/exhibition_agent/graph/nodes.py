"""Supervisor 节点：select_skill → run_skill → emit_trace。

最小图：只有 1 个只读 skill（venue.schedule.query），select_skill 直接选中。
不引入 LangChain Agent/Chain，只用 LangGraph StateGraph 编排。
"""

from __future__ import annotations

from typing import Any

from agent_core.logging import get_logger

from exhibition_agent.contract.envelope import DataClassification, EgressDecision, Readiness
from exhibition_agent.graph.state import ExhibitionAgentState
from exhibition_agent.model_router import route_model
from exhibition_agent.observability.metrics import get_default_registry
from exhibition_agent.observability.otel import span
from exhibition_agent.observability.trace import TraceRecord, now_ms
from exhibition_agent.skills.base_skill import BaseSkill, SkillContext, SkillResult
from exhibition_agent.skills.data_analysis import DataAnalysisQuerySkill
from exhibition_agent.skills.venue_schedule_query import VenueScheduleQuerySkill

logger = get_logger(__name__)

# Skill 注册表（Supervisor 路由分派）。
# 图节点集合保持 select_skill → run_skill → emit_trace 不变（INV-10 结构守卫），
# 多 skill 经 run_skill 节点内分派执行，不新增 LangGraph 节点。
_VENUE_SKILL = VenueScheduleQuerySkill()
_DATA_ANALYSIS_SKILL = DataAnalysisQuerySkill()
_SKILLS: dict[str, BaseSkill] = {
    _VENUE_SKILL.name: _VENUE_SKILL,
    _DATA_ANALYSIS_SKILL.name: _DATA_ANALYSIS_SKILL,
}
_DEFAULT_SKILL: BaseSkill = _VENUE_SKILL


def select_skill(state: ExhibitionAgentState) -> dict[str, Any]:
    """选 skill：params.skill 显式指定 → params.nl_query → 默认 venue.schedule.query。"""
    params = state.get("params", {})
    explicit = params.get("skill")
    if isinstance(explicit, str) and explicit in _SKILLS:
        return {"skill_name": explicit, "latency_start_ms": now_ms()}
    if isinstance(explicit, str) and explicit:
        logger.warning("未知 skill: %s，回退默认", explicit)
        return {
            "skill_name": _DEFAULT_SKILL.name,
            "latency_start_ms": now_ms(),
            "skill_error": f"unknown skill: {explicit}",
        }
    if "nl_query" in params:
        return {"skill_name": _DATA_ANALYSIS_SKILL.name, "latency_start_ms": now_ms()}
    return {"skill_name": _DEFAULT_SKILL.name, "latency_start_ms": now_ms()}


async def run_skill(state: ExhibitionAgentState) -> dict[str, Any]:
    """执行 skill（按 skill_name 分派），处理结果（包 span + metrics 记录）。"""
    skill_error = state.get("skill_error")
    if skill_error:
        return {
            "skill_result": None,
            "answer": f"未知 skill: {skill_error}",
            "error": "UNKNOWN_SKILL",
            "sql_statements": state.get("sql_statements", []),
        }
    skill_name = state.get("skill_name", _DEFAULT_SKILL.name)
    skill = _SKILLS.get(skill_name, _DEFAULT_SKILL)
    registry = state.get("metrics_registry") or get_default_registry()
    ec = state["execution_context"]

    ctx = SkillContext(
        execution_context=state["execution_context"],
        execution_context_header=state["execution_context_header"],
        warehouse_client=state["warehouse_client"],
        context_mode=state.get("context_mode", "jwt"),
        extra_headers=state.get("extra_headers"),
    )
    params = state.get("params", {})

    start_ms = now_ms()
    try:
        with span(
            f"exhibition_agent.skill.{skill_name}",
            request_id=ec.request_id,
            tenant_id=ec.tenant_id,
            skill=skill_name,
        ):
            result: SkillResult = await skill.run(params, ctx)
    except Exception as exc:  # noqa: BLE001
        logger.exception("skill 执行异常：%s", exc)
        registry.record_latency(skill_name, now_ms() - start_ms)
        raw_code = getattr(exc, "code", None)
        # ErrorCode 是 str Enum：str() 会得到 "ErrorCode.XXX"，必须取 .value
        error_code = raw_code.value if hasattr(raw_code, "value") else str(raw_code or type(exc).__name__)
        registry.record_error_code(error_code)
        return {
            "skill_result": None,
            "answer": "内部错误，请重试",
            "error": error_code,
            "sql_statements": state.get("sql_statements", []),
        }

    latency_ms = now_ms() - start_ms
    registry.record_latency(skill_name, latency_ms)
    registry.record_readiness(result.readiness.value)
    if result.error_code:
        registry.record_error_code(result.error_code)

    # Model Router 事前拦截（F02 兜底）：classification 触发出域 DENY → 拒绝展示，
    # 防 warehouse 漏标 EgressDenied。emit_trace 仍会记录 trace（egress_decision=DENY）。
    decision = route_model(result.classification)
    if decision.egress_decision == EgressDecision.DENY:
        logger.warning(
            "Model Router 事前拦截：skill=%s classification=%s → 拒绝展示",
            skill_name,
            result.classification.value,
        )
        denied_result = SkillResult(
            answer="数据出域策略未通过，拒绝回答",
            readiness=Readiness.NOT_CONNECTED,
            classification=result.classification,
            error_code="EGRESS_DENIED",
            egress_decision=EgressDecision.DENY,
        )
        return {
            "skill_result": denied_result,
            "answer": denied_result.answer,
            "error": "EGRESS_DENIED",
            "sql_statements": state.get("sql_statements", []),
        }

    return {
        "skill_result": result,
        "answer": result.answer,
        "error": result.error_code,
        "sql_statements": state.get("sql_statements", []),
    }


def emit_trace(state: ExhibitionAgentState) -> dict[str, Any]:
    """组装 C4 trace 并记录（11 字段缺一不可）。"""
    result: SkillResult | None = state.get("skill_result")
    ec = state["execution_context"]
    start_ms = state.get("latency_start_ms", now_ms())
    latency_ms = now_ms() - start_ms

    if result is None:
        # error 路径：model 经 route_model 决策（INTERNAL → stub-private-qwen），不硬编码
        _err_decision = route_model(DataClassification.INTERNAL)
        trace = TraceRecord(
            request_id=ec.request_id,
            tenant_id=ec.tenant_id,
            skill=state.get("skill_name", "unknown"),
            latency_ms=latency_ms,
            readiness="NOT_CONNECTED",
            data_classification="INTERNAL",
            egress_decision=EgressDecision.DENY.value,
            model=_err_decision.model,
            cost=0.0,
            retrieval_hit_ids=[],
            error_code=state.get("error"),
        )
    else:
        decision = route_model(result.classification)
        trace = TraceRecord(
            request_id=ec.request_id,
            tenant_id=ec.tenant_id,
            skill=state.get("skill_name", _DEFAULT_SKILL.name),
            latency_ms=latency_ms,
            readiness=result.readiness.value,
            data_classification=result.classification.value,
            egress_decision=decision.egress_decision.value,
            model=decision.model,
            cost=decision.cost,
            retrieval_hit_ids=result.retrieval_hit_ids,
            error_code=result.error_code,
        )

    recorder = state.get("trace_recorder")
    if recorder is not None:
        recorder.record(trace)

    registry = state.get("metrics_registry") or get_default_registry()
    if trace.error_code == "SCOPE_DENIED":
        registry.record_scope_denied()
    if trace.error_code == "KNOWLEDGE_NOT_PUBLISHED":
        registry.record_knowledge_not_published()
    # readiness_missing 仅在"数值响应缺 readiness 判 fail"的真实路径记录
    # （NOT_CONNECTED 是合法 readiness 值，不等于缺 readiness）
    if result is not None and result.data.get("readiness_missing"):
        registry.record_readiness_missing()

    return {"trace": trace}
