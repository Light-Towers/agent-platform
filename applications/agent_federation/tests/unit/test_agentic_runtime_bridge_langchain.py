"""AgenticRuntimeBridge → LangChain 工具 集成测试（Phase D 联邦侧，不拉起 deepagents）。

验证：联邦能力经 discover 转为 LangChain 工具后，agent 调用这些工具会经
``RuntimeToolCaller`` → ``runtime.delegate`` 进入统一 Skill Runtime 治理
（架构不变量 #4：Agentic 不绕过统一 Runtime）。
"""

from __future__ import annotations

import os

# 确保 agent.llm / main_agent 在 import 时成功初始化（无真实 key 的测试桩）
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("OPENAI_BASE_URL", "http://localhost/v1")

import pytest
from agent_runtime.skills.registry import Skill, SkillKind, SkillRegistry


class _FakeRuntime:
    """记录 delegate 调用的伪 Runtime（不依赖真实治理链）。"""

    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry
        self.delegate_calls: list[tuple[str, dict]] = []

    async def delegate(self, name: str, **kwargs: object):
        self.delegate_calls.append((name, kwargs))
        skill = self.registry._capabilities[name]
        return await skill.executor(**kwargs)


async def _db_executor(**kwargs):
    return {"rows": [kwargs]}


async def test_bridged_tools_route_through_runtime_delegate():
    from agent_federation.planners.agentic_runtime_bridge import (
        build_bridged_langchain_tools,
    )

    reg = SkillRegistry()
    reg.register(
        Skill(
            "db_query",
            "查询数据库",
            SkillKind.FUNCTION,
            _db_executor,
            input_schema={
                "type": "object",
                "properties": {"sql": {"type": "string"}},
                "required": ["sql"],
            },
        )
    )
    rt = _FakeRuntime(reg)

    tools = build_bridged_langchain_tools(rt, "查一下订单")
    assert len(tools) == 1
    tool = tools[0]
    assert tool.name == "db_query"

    out = await tool.ainvoke({"sql": "select 1"})
    assert out == {"rows": [{"sql": "select 1"}]}
    # 关键：工具调用经 RuntimeToolCaller → runtime.delegate，而非直接执行器
    assert rt.delegate_calls == [("db_query", {"sql": "select 1"})]


async def test_bridged_tools_route_to_distinct_capabilities():
    """回归：每个桥接工具须路由到自身的能力名（捕获循环内闭包误捕获变量）。

    若 ``_invoke`` 闭包在循环中捕获 ``cname``（late-binding），所有工具都会路由到
    最后一个能力名——本测试用两个能力断言各自路由正确。
    """
    from agent_federation.planners.agentic_runtime_bridge import (
        build_bridged_langchain_tools,
    )

    reg = SkillRegistry()
    schema = {
        "type": "object",
        "properties": {"q": {"type": "string"}},
        "required": ["q"],
    }
    reg.register(
        Skill("db_query", "查询数据库", SkillKind.FUNCTION, _db_executor, input_schema=schema)
    )
    reg.register(
        Skill("net_search", "网络搜索", SkillKind.FUNCTION, _db_executor, input_schema=schema)
    )
    rt = _FakeRuntime(reg)

    tools = build_bridged_langchain_tools(rt, "查一下订单")
    assert {t.name for t in tools} == {"db_query", "net_search"}

    await tools[0].ainvoke({"q": "a"})
    await tools[1].ainvoke({"q": "b"})
    # 顺序与各自工具名对应，而非都被最后一个能力名吞掉（循环内闭包误捕获变量会失败）
    assert rt.delegate_calls == [("db_query", {"q": "a"}), ("net_search", {"q": "b"})]


async def test_bridge_disabled_returns_default_tools():
    from agent_federation.agent.main_agent import _maybe_attach_bridged_tools
    from agent_federation.planners.agentic_runtime_bridge import bridge_enabled

    # 不依赖环境变量：直接验证默认分支（bridge 关闭时原样返回）
    if bridge_enabled():
        pytest.skip("AGENTIC_RUNTIME_BRIDGE 已开启，跳过默认分支断言")
    base = [object()]
    assert _maybe_attach_bridged_tools(base, "q") is base
