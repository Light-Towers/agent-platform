"""venue.schedule.query skill 测试（只读，v1.2 直接 REST）。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from exhibition_agent.client.contract_errors import EgressDeniedError
from exhibition_agent.contract.envelope import EgressDecision, Readiness
from exhibition_agent.foundation.skill_router import _load_catalog
from exhibition_agent.skills.base_skill import SkillContext
from exhibition_agent.skills.venue_schedule_query import VenueScheduleQuerySkill
from exhibition_agent.testing_helpers import ctx, ctx_header

# 端点从 catalog 取（tool_catalog.json 是端点的唯一真相源）：测试不重复硬编码路径，
# 这样 skill 与 catalog 漂移时本文件会红，而不是两边各写一份互相掩盖。
VENUE_SCHEDULE_ENDPOINT = _load_catalog()["tools"]["venue_schedule"]["endpoint"]


@pytest.fixture
def skill_context(warehouse_client):
    context = ctx()
    return SkillContext(
        execution_context=context,
        execution_context_header=ctx_header(context),
        warehouse_client=warehouse_client,
        routed_endpoint=VENUE_SCHEDULE_ENDPOINT,
        context_mode="jwt",
    )


async def test_skill_normal_query(skill_context):
    """正常 200 + data_readiness.level=complete → SkillResult.readiness=READY。"""
    skill = VenueScheduleQuerySkill()
    result = await skill.run({"venue_id": "vn-001"}, skill_context)
    assert result.readiness == Readiness.READY
    assert "保利世贸博览馆" in result.answer
    assert len(result.citations) >= 1


async def test_skill_scope_denied(warehouse_client):
    """403 SCOPE_DENIED → SkillResult.error_code=SCOPE_DENIED。"""
    context = ctx()
    sc = SkillContext(
        execution_context=context,
        execution_context_header=ctx_header(context),
        warehouse_client=warehouse_client,
        routed_endpoint=VENUE_SCHEDULE_ENDPOINT,
        extra_headers={"X-Mock-Scenario": "scope_denied"},
    )
    skill = VenueScheduleQuerySkill()
    result = await skill.run({"venue_id": "vn-001"}, sc)
    assert result.error_code == "SCOPE_DENIED"
    assert "无权" in result.answer


async def test_skill_knowledge_not_published(warehouse_client):
    """404 KNOWLEDGE_NOT_PUBLISHED → SkillResult.error_code=KNOWLEDGE_NOT_PUBLISHED。"""
    context = ctx()
    sc = SkillContext(
        execution_context=context,
        execution_context_header=ctx_header(context),
        warehouse_client=warehouse_client,
        routed_endpoint=VENUE_SCHEDULE_ENDPOINT,
        extra_headers={"X-Mock-Scenario": "knowledge_not_published"},
    )
    skill = VenueScheduleQuerySkill()
    result = await skill.run({"venue_id": "vn-001"}, sc)
    assert result.error_code == "KNOWLEDGE_NOT_PUBLISHED"
    assert "未发布" in result.answer


async def test_skill_data_not_connected_422_answers_pending(warehouse_client):
    """422 DATA_NOT_CONNECTED → 答'待接入'（INV-10 422 路径）。"""
    context = ctx()
    sc = SkillContext(
        execution_context=context,
        execution_context_header=ctx_header(context),
        warehouse_client=warehouse_client,
        routed_endpoint=VENUE_SCHEDULE_ENDPOINT,
        extra_headers={"X-Mock-Scenario": "data_not_connected_422"},
    )
    skill = VenueScheduleQuerySkill()
    result = await skill.run({"venue_id": "vn-001"}, sc)
    assert result.answer == "该指标待接入"
    assert result.error_code == "DATA_NOT_CONNECTED"


async def test_skill_data_not_connected_200_answers_pending(warehouse_client):
    """200 + data_readiness.level=pending → 答'待接入'（INV-10 200 data_readiness 路径）。"""
    context = ctx()
    sc = SkillContext(
        execution_context=context,
        execution_context_header=ctx_header(context),
        warehouse_client=warehouse_client,
        routed_endpoint=VENUE_SCHEDULE_ENDPOINT,
        extra_headers={"X-Mock-Scenario": "data_not_connected"},
    )
    skill = VenueScheduleQuerySkill()
    result = await skill.run({"venue_id": "vn-001"}, sc)
    assert result.answer == "该指标待接入"
    assert result.error_code == "DATA_NOT_CONNECTED"
    assert result.readiness == Readiness.NOT_CONNECTED


async def test_skill_egress_denied_uses_enum():
    """EgressDeniedError → egress_decision 为 EgressDecision.DENY 枚举（非裸字符串）。"""
    context = ctx()
    mock_client = AsyncMock()
    mock_client.get_rest = AsyncMock(side_effect=EgressDeniedError("test egress denied"))
    sc = SkillContext(
        execution_context=context,
        execution_context_header=ctx_header(context),
        warehouse_client=mock_client,
        routed_endpoint=VENUE_SCHEDULE_ENDPOINT,
        context_mode="jwt",
    )
    skill = VenueScheduleQuerySkill()
    result = await skill.run({"venue_id": "vn-001"}, sc)
    assert result.egress_decision == EgressDecision.DENY
    assert result.egress_decision.value == "DENY"
