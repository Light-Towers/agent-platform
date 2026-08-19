"""P5：工具注册表 + 动态角色规划。

验证 TOOL_REGISTRY 单一事实来源、角色到工具的映射、normalize 兜底、以及
get_main_agent_for_task 的 LRU 缓存行为（使用假 agent，不构造真实 LLM/deep agent）。

注意：pytest 收集本模块会 import ``agent.main_agent``（其顶层构造 model），
故在 import 前注入 dummy 环境变量，避免无 OPENAI 配置时模块加载失败。
"""
import asyncio
import os

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("OPENAI_BASE_URL", "http://localhost:9999/v1")

import agent.main_agent as ma
from agent.tool_registry import TOOL_REGISTRY, ROLE_TOOLS, get_tools_for_roles, normalize_roles


def test_tool_registry_consistency():
    # 每个 role 引用的工具名必须都在注册表里
    for role, names in ROLE_TOOLS.items():
        for n in names:
            assert n in TOOL_REGISTRY, f"role {role} 引用了未注册工具 {n}"
    # 全量工具：每个注册项都应能解析（或优雅跳过），不应抛错
    from agent.tool_registry import _resolve

    resolved = sum(1 for n in TOOL_REGISTRY if _resolve(n) is not None)
    assert len(get_tools_for_roles(None)) == resolved


def test_get_tools_for_roles_filters_and_dedups():
    tools = get_tools_for_roles(["data", "knowledge"])
    names = {getattr(t, "name", getattr(t, "__name__", "")) for t in tools}
    assert "execute_sql_query" in names
    assert "zhiku_retrieve" in names
    assert "read_file_content" in names


def test_normalize_roles_drops_unknown_and_keeps_base():
    out = normalize_roles(["data", "bogus_role", "search"])
    assert "data" in out
    assert "search" in out
    assert "bogus_role" not in out
    assert "files" in out  # BASE_ROLES 必须保留


def test_plan_roles_parse_and_fallback(monkeypatch):
    async def fake_ainvoke(*args, **kwargs):
        return type("R", (), {"content": '{"roles": ["data", "search"]}'})()

    monkeypatch.setattr(type(ma.model), "ainvoke", fake_ainvoke)
    roles = asyncio.run(ma._plan_roles("帮我查销售额并联网核实"))
    assert "data" in roles and "search" in roles

    async def fake_ainvoke2(*args, **kwargs):
        return type("R", (), {"content": "```json\n{\"roles\": [\"knowledge\"]}\n```"})()

    monkeypatch.setattr(type(ma.model), "ainvoke", fake_ainvoke2)
    roles2 = asyncio.run(ma._plan_roles("查知识库"))
    assert roles2 == ["files", "knowledge"]


def test_plan_roles_failure_returns_none(monkeypatch):
    async def boom(prompt):
        raise RuntimeError("llm down")

    monkeypatch.setattr(type(ma.model), "ainvoke", boom)
    assert asyncio.run(ma._plan_roles("x")) is None


def test_dynamic_agent_lru_cache(monkeypatch):
    """验证 get_main_agent_for_task 按 role-spec 缓存，超出容量 LRU 淘汰。"""
    import asyncio as _asyncio

    calls = {"n": 0}

    def fake_create(**kwargs):
        calls["n"] += 1
        return {"fake_agent": True}

    async def fake_cp():
        return None

    monkeypatch.setattr(ma, "create_deep_agent", fake_create)
    monkeypatch.setattr(ma, "_create_checkpointer", fake_cp)
    monkeypatch.setattr(ma, "_create_store", fake_cp)
    monkeypatch.setattr(ma, "_main_checkpointer", None)
    monkeypatch.setattr(ma, "_main_store", None)
    monkeypatch.setattr(ma, "_build_subagents", lambda: [])
    monkeypatch.setattr(ma, "_build_middleware", lambda: None)
    monkeypatch.setattr(ma, "main_agent_content", {"system_prompt": ""})
    monkeypatch.setattr(ma, "planner_content", {})
    monkeypatch.setenv("PLANNER_ENABLED", "false")

    ma._ROLE_CACHE.clear()
    ma._ROLE_CACHE_MAX = 2

    async def run():
        a1 = await ma.get_main_agent_for_task(["data", "files"])
        a2 = await ma.get_main_agent_for_task(["data", "files"])  # 命中缓存
        assert a1 is a2
        await ma.get_main_agent_for_task(["search", "files"])
        await ma.get_main_agent_for_task(["knowledge", "files"])
        # 容量 2，插入第三类会淘汰最旧 -> 构造次数 = 3
        return calls["n"]

    assert _asyncio.run(run()) == 3
    assert len(ma._ROLE_CACHE) == 2
