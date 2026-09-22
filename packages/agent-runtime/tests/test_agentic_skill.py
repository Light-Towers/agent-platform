"""AgenticPlanner.to_skill() 收敛测试：SkillKind.AGENT 契约。"""

from __future__ import annotations

import pytest

from agent_runtime.planner.agentic import AgenticPlanner, register_agentic_executor_factory
from agent_runtime.skills.registry import SkillKind, SkillRegistry


@pytest.mark.asyncio
async def test_to_skill_returns_agent_kind():
    async def fake_executor(question, workspace_id, main_agent=None):
        return f"answer:{question}"

    register_agentic_executor_factory(lambda: fake_executor)
    planner = AgenticPlanner()
    skill = planner.to_skill()
    assert skill.name == "agentic"
    assert skill.kind == SkillKind.AGENT
    assert "question" in skill.input_schema["properties"]


@pytest.mark.asyncio
async def test_to_skill_executor_callable():
    async def fake_executor(question, workspace_id, main_agent=None):
        return f"result:{question}@{workspace_id}"

    register_agentic_executor_factory(lambda: fake_executor)
    planner = AgenticPlanner()
    skill = planner.to_skill()
    result = await skill.executor(question="hello", workspace_id="ws1")
    assert result == "result:hello@ws1"


@pytest.mark.asyncio
async def test_to_skill_executor_with_main_agent():
    async def fake_executor(question, workspace_id, main_agent=None):
        return f"{question}:{main_agent}"

    register_agentic_executor_factory(lambda: fake_executor)
    planner = AgenticPlanner()
    skill = planner.to_skill()
    result = await skill.executor(question="q", workspace_id="w", main_agent="agent_obj")
    assert result == "q:agent_obj"


@pytest.mark.asyncio
async def test_to_skill_default_workspace():
    async def fake_executor(question, workspace_id, main_agent=None):
        return workspace_id

    register_agentic_executor_factory(lambda: fake_executor)
    planner = AgenticPlanner()
    skill = planner.to_skill()
    result = await skill.executor(question="q")
    assert result == "default"


def test_to_skill_with_permissions():
    async def fake_executor(question, workspace_id, main_agent=None):
        return "ok"

    register_agentic_executor_factory(lambda: fake_executor)
    planner = AgenticPlanner()
    skill = planner.to_skill(permissions={"admin"})
    assert "admin" in skill.permissions


def test_to_skill_with_timeout():
    async def fake_executor(question, workspace_id, main_agent=None):
        return "ok"

    register_agentic_executor_factory(lambda: fake_executor)
    planner = AgenticPlanner()
    skill = planner.to_skill(timeout_ms=5000)
    assert skill.timeout_ms == 5000


@pytest.mark.asyncio
async def test_to_skill_registered_in_registry():
    async def fake_executor(question, workspace_id, main_agent=None):
        return "registered"

    register_agentic_executor_factory(lambda: fake_executor)
    planner = AgenticPlanner()
    skill = planner.to_skill()
    reg = SkillRegistry()
    reg.register(skill)
    assert "agentic" in reg
    result = await reg.execute("agentic", question="test", workspace_id="ws")
    assert result == "registered"
