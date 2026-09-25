"""agent_core.tools 单元测试。"""

from agent_core.tools.guarded import guarded_invoke, wrap_tool
from agent_core.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------
def test_registry_register_and_get():
    reg = ToolRegistry()
    reg.register("search", lambda state: {"results": []}, enabled=True, timeout_s=2.0)
    entry = reg.get("search")
    assert entry is not None
    assert entry.name == "search"
    assert entry.enabled is True
    assert entry.timeout_s == 2.0


def test_registry_get_missing():
    reg = ToolRegistry()
    assert reg.get("nonexistent") is None


def test_registry_enabled_names():
    reg = ToolRegistry()
    reg.register("a", lambda s: {}, enabled=True)
    reg.register("b", lambda s: {}, enabled=False)
    reg.register("c", lambda s: {}, enabled=True)
    assert reg.enabled_names() == ["a", "c"]


def test_registry_overwrite():
    reg = ToolRegistry()
    reg.register("tool", lambda s: {"v": 1})
    reg.register("tool", lambda s: {"v": 2})
    assert len(reg.list()) == 1


# ---------------------------------------------------------------------------
# guarded_invoke
# ---------------------------------------------------------------------------
def test_guarded_invoke_success():
    def tool(state):
        return {"answer": state["query"]}

    result = guarded_invoke(tool, {"query": "hello"}, timeout_s=1.0)
    assert result == {"answer": "hello"}


def test_guarded_invoke_timeout():
    import time

    def slow_tool(state):
        time.sleep(0.3)
        return {"late": True}

    result = guarded_invoke(slow_tool, {}, timeout_s=0.05)
    assert result == {}


def test_guarded_invoke_exception_returns_empty():
    def bad_tool(state):
        raise RuntimeError("boom")

    result = guarded_invoke(bad_tool, {}, timeout_s=1.0)
    assert result == {}


def test_guarded_invoke_non_dict_returns_empty():
    def weird_tool(state):
        return "not a dict"

    result = guarded_invoke(weird_tool, {}, timeout_s=1.0)
    assert result == {}


def test_guarded_invoke_with_invoke_method():
    class MyTool:
        def invoke(self, state):
            return {"data": state["x"] * 2}

    result = guarded_invoke(MyTool(), {"x": 21}, timeout_s=1.0)
    assert result == {"data": 42}


# ---------------------------------------------------------------------------
# wrap_tool
# ---------------------------------------------------------------------------
def test_wrap_tool_enabled():
    def tool(state):
        return {"ok": True}

    wrapped = wrap_tool(tool, enabled=True, timeout_s=1.0)
    assert wrapped({}) == {"ok": True}


def test_wrap_tool_disabled():
    def tool(state):
        return {"ok": True}

    wrapped = wrap_tool(tool, enabled=False, timeout_s=1.0)
    assert wrapped({}) == {}
