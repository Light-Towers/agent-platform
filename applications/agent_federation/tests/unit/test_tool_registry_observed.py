"""批 2 回归：tool_registry 统一出口（observe_tool 包装）+ 挂载矩阵关键约束。

- get_tool 返回包装副本且元数据逐字段保留（W4）；
- 双重/三重挂载工具（方案挂载矩阵）全部可经统一出口取得；
- get_tools_for_roles 动态路径同样产出包装工具（封死 C1 旁路）；
- DISPLAY_NAMES 覆盖全部注册工具（防新增工具漏配展示名漂移）。

行为级事件断言在 kernel（packages/agent-core/tests/test_tool_observability.py）。
"""

import agent.tool_registry as agent_tool_registry
from agent.tool_registry import DISPLAY_NAMES, TOOL_REGISTRY, get_tool, get_tools_for_roles

# 挂载矩阵（tool-mount-matrix-2026-09-25.md）：三重/双重挂载工具必须在册
_DOUBLE_MOUNTED = {
    "generate_markdown",
    "convert_md_to_pdf",
    "read_file_content",
    "execute_sql_query",
    "get_table_data",
    "list_sql_tables",
    "knowledge_retrieve",
    "internet_search",
    "execute_python_code",
}


def test_registry_covers_mount_matrix():
    """挂载矩阵中的非死代码工具必须全部在 TOOL_REGISTRY（批 2 收编完整性）。"""
    assert _DOUBLE_MOUNTED <= set(TOOL_REGISTRY)


def test_get_tool_returns_wrapped_copy_with_metadata():
    import tools.db_tools as db_module

    raw = db_module.execute_sql_query
    wrapped = get_tool("execute_sql_query")

    assert wrapped is not raw, "统一出口必须返回包装副本，而非裸 @tool 对象"
    assert wrapped.name == raw.name
    assert wrapped.description == raw.description
    assert wrapped.args == raw.args


def test_get_tool_cached_idempotent():
    assert get_tool("knowledge_retrieve") is get_tool("knowledge_retrieve")


def test_double_mounted_tools_resolvable_via_single_exit():
    for name in sorted(_DOUBLE_MOUNTED):
        assert get_tool(name) is not None, f"工具 {name} 无法经统一出口取得"


def test_get_tools_for_roles_returns_wrapped_tools():
    tools = get_tools_for_roles(["data"])
    names = {t.name for t in tools}
    # data 角色：execute_sql_query（REG）+ read_file_content（REG）
    assert {"execute_sql_query", "read_file_content"} <= names


def test_display_names_cover_registry():
    """每个在册工具都应有展示名映射（防 tool_name 取值漂移遗漏，方案 §3.2④）。"""
    missing = set(TOOL_REGISTRY) - set(DISPLAY_NAMES)
    assert not missing, f"缺少展示名映射的工具: {sorted(missing)}"


def test_get_tool_emits_paired_start_outcome(monkeypatch):
    """S6（评审）：统一出口 get_tool 真实调用须产出成对 tool_start + tool_outcome
    （封死「registry 包装但未真正接观测」的回归）；display_name 映射生效（C3）。

    用 monkeypatch 注入一个离线安全的合成工具，避免触发生产工具的外部依赖/写盘。
    """

    import importlib

    from langchain_core.tools import StructuredTool

    from agent_core.monitor import monitor as _global_monitor

    captured: list[dict] = []

    def _on_start(e: dict) -> None:
        captured.append(e)

    def _on_outcome(e: dict) -> None:
        captured.append(e)

    def _selftest_fn() -> str:
        """selftest fake tool."""
        return "selftest-ok"

    fake_tool = StructuredTool.from_function(
        func=_selftest_fn, name="_selftest_fake", description="selftest fake"
    )

    class _FakeModule:
        _selftest_fake = fake_tool

    _real_import = importlib.import_module

    def _patched_import(path: str):
        if path == "tools._selftest_fake":
            return _FakeModule()
        return _real_import(path)

    monkeypatch.setattr(importlib, "import_module", _patched_import)
    monkeypatch.setitem(agent_tool_registry.TOOL_REGISTRY, "_selftest_fake", "tools._selftest_fake:_selftest_fake")
    monkeypatch.setitem(agent_tool_registry.DISPLAY_NAMES, "_selftest_fake", "自测工具")

    _global_monitor.on("tool_start", _on_start)
    _global_monitor.on("tool_outcome", _on_outcome)
    try:
        wrapped = agent_tool_registry.get_tool("_selftest_fake")
        assert wrapped is not None, "统一出口必须返回包装副本"
        result = wrapped.invoke({})
        assert result == "selftest-ok"
    finally:
        _global_monitor.off("tool_start", _on_start)
        _global_monitor.off("tool_outcome", _on_outcome)
        # 清缓存避免污染其它测试（合成名唯一，正常不会冲突）
        agent_tool_registry._RESOLVED.pop("_selftest_fake", None)
        agent_tool_registry._WRAPPED_CACHE.pop("_selftest_fake", None)

    starts = [e for e in captured if e["event"] == "tool_start"]
    outcomes = [e for e in captured if e["event"] == "tool_outcome"]
    assert len(starts) == 1, f"期望恰好 1 个 tool_start，实得 {len(starts)}"
    assert len(outcomes) == 1, f"期望恰好 1 个 tool_outcome，实得 {len(outcomes)}"
    # display_name 映射生效（C3）：事件 tool_name = 展示名
    assert starts[0]["data"]["tool_name"] == "自测工具"
    assert outcomes[0]["data"]["tool_name"] == "自测工具"
    assert outcomes[0]["data"]["outcome"] == "success"
