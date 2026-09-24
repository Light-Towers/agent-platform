"""as_remote_skill + as_dag_skill 单元测试：薄包装契约。"""

from __future__ import annotations

import pytest

from agent_runtime.skills.dag import as_dag_skill
from agent_runtime.skills.registry import SkillKind
from agent_runtime.skills.remote import as_remote_skill


@pytest.mark.asyncio
async def test_as_remote_skill_basic():
    async def fetch(url):
        return f"content from {url}"

    skill = as_remote_skill("fetch", "远程获取", fetch)
    assert skill.name == "fetch"
    assert skill.description == "远程获取"
    assert skill.kind == SkillKind.REMOTE
    result = await skill.executor(url="http://example.com")
    assert "example.com" in result


@pytest.mark.asyncio
async def test_as_remote_skill_with_schema_and_permissions():
    async def invoke(**kwargs):
        return "ok"

    schema = {"type": "object", "properties": {"q": {"type": "string"}}}
    skill = as_remote_skill(
        "svc", "服务", invoke,
        input_schema=schema,
        timeout_ms=3000,
        permissions={"read"},
    )
    assert skill.input_schema == schema
    assert skill.timeout_ms == 3000
    assert "read" in skill.permissions


@pytest.mark.asyncio
async def test_as_remote_skill_empty_permissions():
    async def invoke(**kwargs):
        return "ok"

    skill = as_remote_skill("svc", "服务", invoke)
    assert skill.permissions == frozenset()


@pytest.mark.asyncio
async def test_as_dag_skill_basic():
    async def run_pipeline(**kwargs):
        return {"summary": kwargs.get("query", "")}

    skill = as_dag_skill("pipeline", "流水线", run_pipeline)
    assert skill.name == "pipeline"
    assert skill.description == "流水线"
    assert skill.kind == SkillKind.WORKFLOW
    result = await skill.executor(query="test")
    assert result["summary"] == "test"


@pytest.mark.asyncio
async def test_as_dag_skill_with_schema_and_permissions():
    async def run_dag(**kwargs):
        return "done"

    schema = {"type": "object", "properties": {"input": {"type": "string"}}}
    skill = as_dag_skill(
        "dag", "DAG", run_dag,
        input_schema=schema,
        timeout_ms=5000,
        permissions={"admin"},
    )
    assert skill.input_schema == schema
    assert skill.timeout_ms == 5000
    assert "admin" in skill.permissions
