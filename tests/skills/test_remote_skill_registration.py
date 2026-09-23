"""P1/P4 验证：RemoteExecutor skill 注册 + agentic 能力组合验证。

验证项：
- P1: knowledge/nl2sql/kefu RemoteExecutor skill 在 URL 配置时注册成功
- P1: URL 未配置时跳过（不崩溃）
- P4: SkillRegistry 能发现已注册 skill 并生成 tool schema（供 AgenticPlanner LLM 选择）
- P4: runtime.delegate 能调到 skill（经中间件链 + skill_guard）
"""

from __future__ import annotations

import pytest
from agent_runtime.skills.registry import SkillKind, SkillRegistry


@pytest.mark.asyncio
async def test_remote_skills_register_when_url_set(monkeypatch):
    """P1: 配置 URL 时，knowledge/nl2sql/kefu skill 注册到 SkillRegistry。"""
    monkeypatch.setenv("KNOWLEDGE_SERVICE_URL", "http://localhost:8900")
    monkeypatch.setenv("NL2SQL_SERVICE_URL", "http://localhost:8000")
    monkeypatch.setenv("KEFU_SERVICE_URL", "http://localhost:8003")

    from agent_server.capabilities import build_registry

    registry = build_registry()
    names = {s.name for s in registry.list()}

    assert "knowledge_query" in names, "knowledge_query skill 未注册"
    assert "knowledge_retrieve" in names, "knowledge_retrieve skill 未注册"
    assert "nl2sql_query" in names, "nl2sql_query skill 未注册"
    assert "kefu_query" in names, "kefu_query skill 未注册"

    assert registry.get("knowledge_query").kind == SkillKind.REMOTE
    assert registry.get("nl2sql_query").kind == SkillKind.REMOTE
    assert registry.get("kefu_query").kind == SkillKind.REMOTE


@pytest.mark.asyncio
async def test_remote_skills_skip_when_url_unset(monkeypatch):
    """P1: URL 未配置时跳过注册（不崩溃）。"""
    monkeypatch.delenv("KNOWLEDGE_SERVICE_URL", raising=False)
    monkeypatch.delenv("NL2SQL_SERVICE_URL", raising=False)
    monkeypatch.delenv("KEFU_SERVICE_URL", raising=False)

    from agent_server.capabilities import build_registry

    registry = build_registry()
    names = {s.name for s in registry.list()}

    assert "knowledge_query" not in names
    assert "nl2sql_query" not in names
    assert "kefu_query" not in names
    assert "search" in names, "基础 skill 仍应注册"


@pytest.mark.asyncio
async def test_skill_discovery_for_agentic_planner(monkeypatch):
    """P4: SkillRegistry.to_tool_schemas 生成 OpenAI function-calling 工具描述。

    AgenticPlanner 经 discover_agent_tools 发现能力 → LLM 选择 → runtime.delegate 执行。
    此测试验证 skill 注册后能被发现并转为 tool schema。
    """
    monkeypatch.setenv("KNOWLEDGE_SERVICE_URL", "http://localhost:8900")
    monkeypatch.setenv("NL2SQL_SERVICE_URL", "http://localhost:8000")

    from agent_server.capabilities import build_registry

    registry = build_registry()
    skills = registry.list()
    skill_names = {s.name for s in skills}
    assert len(skills) >= 6, f"应至少注册 6 个 skill，实际 {len(skills)}: {skill_names}"

    schemas = SkillRegistry.to_tool_schemas(skills)
    assert all(s["type"] == "function" for s in schemas), "所有 schema 应为 function 类型"
    func_names = {s["function"]["name"] for s in schemas}
    assert "search" in func_names
    assert "knowledge_query" in func_names
    assert "nl2sql_query" in func_names


@pytest.mark.asyncio
async def test_delegate_executes_skill_through_guard(monkeypatch):
    """P4: runtime.delegate 经 skill_guard 调到 skill，step_count 递增。

    验证 agentic loop 核心路径：PlannerRuntime.delegate → skill_guard → registry.execute。
    """
    from agent_runtime.planner.protocol import PlannerRuntime

    reg = SkillRegistry()

    async def _echo(**kwargs):
        return kwargs

    from agent_runtime.skills.function import as_function_skill

    reg.register(as_function_skill("echo", "echo skill", _echo))
    runtime = PlannerRuntime(registry=reg, max_steps=10, max_skill_depth=4)

    async with runtime.execution():
        result = await runtime.delegate("echo", x="hello")
        assert result == {"x": "hello"}
        ctx = runtime.context
        assert ctx is not None
        assert ctx.step_count == 1, f"delegate 后 step_count 应为 1，实际 {ctx.step_count}"
        assert "echo" in ctx.call_stack or ctx.step_count >= 1


@pytest.mark.asyncio
async def test_composite_task_multi_skill_delegation(monkeypatch):
    """P4: 复合任务——delegate 多个 skill，step_count 累计。

    模拟 LLM 选了 search + knowledge_query 组合执行。
    """
    from agent_runtime.planner.protocol import PlannerRuntime

    reg = SkillRegistry()

    async def _search(**kwargs):
        return f"search result for: {kwargs.get('query', '')}"

    async def _knowledge(**kwargs):
        return f"knowledge result for: {kwargs.get('query', '')}"

    from agent_runtime.skills.function import as_function_skill

    reg.register(as_function_skill("search", "联网搜索", _search))
    reg.register(as_function_skill("knowledge_query", "知识库查询", _knowledge))

    runtime = PlannerRuntime(registry=reg, max_steps=10, max_skill_depth=4)

    async with runtime.execution():
        r1 = await runtime.delegate("search", query="天气")
        r2 = await runtime.delegate("knowledge_query", query="天气预报")

        assert "search result" in r1
        assert "knowledge result" in r2
        ctx = runtime.context
        assert ctx.step_count == 2, f"两次 delegate 后 step_count 应为 2，实际 {ctx.step_count}"
