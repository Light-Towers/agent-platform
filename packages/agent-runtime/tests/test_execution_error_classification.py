"""M1.1 执行层异常分类单测（agent-runtime）。

验证 ExecutionGraph 节点错误按分类驱动控制流：
- RETRYABLE → 业务级有限重试后成功（不产 error 事件）；
- FATAL（编程错误）→ 产 error_class=fatal 事件并终止整次执行；
- RECOVERABLE（未知异常）→ 产 error 事件但独立下游仍运行；
- 依赖降级：上游失败 → 下游依赖节点按 recoverable 跳过（不误判 Fatal）。
"""


from agent_runtime.planner.execution_graph import ExecutionGraph, _run_graph_in_place
from agent_runtime.planner.protocol import PlannerRuntime
from agent_runtime.skills.registry import Skill, SkillKind, SkillRegistry


def _registry(skills: dict) -> SkillRegistry:
    reg = SkillRegistry()
    for name, fn in skills.items():
        reg.register(Skill(name, name, SkillKind.FUNCTION, fn))
    return reg


def _graph() -> ExecutionGraph:
    return ExecutionGraph()


async def _collect(runtime, graph):
    events = []
    async with runtime.execution():
        async for ev in _run_graph_in_place(graph, runtime):
            events.append(ev)
    return events


async def test_retryable_retries_then_succeeds():
    state = {"calls": 0}

    async def flaky(**kwargs):
        state["calls"] += 1
        if state["calls"] == 1:
            raise ConnectionError("transient down")
        return {"ok": True}

    g = _graph()
    g.add_node("n1", "flaky", {})
    runtime = PlannerRuntime(registry=_registry({"flaky": flaky}))

    events = await _collect(runtime, g)

    # 重试后成功：无 error 事件，且恰好重试 1 次（首 + 重试）
    assert state["calls"] == 2
    assert not any(ev.type == "error" for ev in events)
    assert any(ev.type == "evidence" for ev in events)


async def test_fatal_aborts_execution():
    ran_n2 = {"v": False}

    async def boom(**kwargs):
        raise TypeError("bad state shape")

    async def flag(**kwargs):
        ran_n2["v"] = True
        return {"x": 1}

    g = _graph()
    g.add_node("n1", "boom", {})
    g.add_node("n2", "flag", input_refs={"x": "node:n1"})  # 依赖 n1 → 层 1
    runtime = PlannerRuntime(registry=_registry({"boom": boom, "flag": flag}))

    events = await _collect(runtime, g)

    # n1 致命 → 终止整次执行：仅一条 fatal error 事件，层 1 的 n2 未运行
    errs = [ev for ev in events if ev.type == "error"]
    assert len(errs) == 1
    assert errs[0].payload.get("error_class") == "fatal"
    assert ran_n2["v"] is False


async def test_recoverable_continues_independent_downstream():
    ran_n2 = {"v": False}

    async def unknown_fail(**kwargs):
        raise RuntimeError("opaque failure")

    async def flag(**kwargs):
        ran_n2["v"] = True
        return {"x": 1}

    g = _graph()
    g.add_node("n1", "ufail", {})
    g.add_node("n2", "flag", {})  # 独立 → 同层
    runtime = PlannerRuntime(registry=_registry({"ufail": unknown_fail, "flag": flag}))

    events = await _collect(runtime, g)

    # n1 未知异常 → recoverable：error 事件 + 独立下游 n2 仍运行
    errs = [ev for ev in events if ev.type == "error"]
    assert len(errs) == 1
    assert errs[0].payload.get("error_class") == "recoverable"
    assert ran_n2["v"] is True


async def test_dependency_skip_on_upstream_failure():
    ran_n2 = {"v": False}

    async def unknown_fail(**kwargs):
        raise RuntimeError("opaque failure")

    async def flag(**kwargs):
        ran_n2["v"] = True
        return {"x": 1}

    g = _graph()
    g.add_node("n1", "ufail", {})
    g.add_node("n2", "flag", input_refs={"x": "node:n1"})  # 依赖失败的上游
    runtime = PlannerRuntime(registry=_registry({"ufail": unknown_fail, "flag": flag}))

    events = await _collect(runtime, g)

    # 下游依赖未就绪 → 降级跳过（recoverable），不误判 Fatal、不运行
    errs = [ev for ev in events if ev.type == "error"]
    assert len(errs) == 2
    assert all(e.payload.get("error_class") == "recoverable" for e in errs)
    assert ran_n2["v"] is False
