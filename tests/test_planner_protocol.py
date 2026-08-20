"""Plan-F Phase 2：Planner 协议 + PlannerRegistry + DeterministicPlanner 测试。

覆盖：协议模型默认值、注册表语义、deterministic 决策（启发式/chitchat/护栏拦截）、
编排执行（事件序列/反思重试/无 LLM 模板合成）、与 golden 路由基线一致。
"""

from __future__ import annotations

import pytest
from agent_runtime.planner.protocol import (
    Plan,
    PlannerContext,
    PlannerRuntime,
    SkillCompositionError,
    StreamEvent,
)
from agent_runtime.planner.registry import PlannerRegistry
from agent_server.planners.deterministic import DeterministicPlanner


class FakeRegistry:
    """最小能力注册表替身：按能力名返回固定 evidence。"""

    def __init__(self, search_evidence: list[str] | None = None, rag_evidence: list[str] | None = None):
        self._search = search_evidence if search_evidence is not None else ["搜索证据一", "搜索证据二"]
        self._rag = rag_evidence if rag_evidence is not None else ["知识库证据一"]

    async def execute(self, name: str, **kwargs):
        if name == "search":
            return self._search
        if name == "rag":
            return self._rag
        if name == "direct":
            return []
        return []


class _FakePlanner(DeterministicPlanner):
    kind = "fake"


# ---------- 协议模型 ----------


def test_plan_defaults():
    plan = Plan(route="rag")
    assert plan.sub_query == ""
    assert plan.reason == ""
    assert plan.notes == {}


def test_stream_event_payload_defaults():
    ev = StreamEvent(type="route", payload={"capability": "rag"})
    assert ev.type == "route"
    assert ev.payload == {"capability": "rag"}
    ev2 = StreamEvent(type="answer")
    assert ev2.payload == {}


def test_planner_context_defaults_and_mcp_fields():
    ctx = PlannerContext(question="问题")
    assert ctx.workspace_id == "default"
    assert ctx.user_id == "default"
    assert ctx.messages == []
    assert ctx.llm is None
    assert ctx.mcp_server == ""
    assert ctx.mcp_tool == ""
    assert ctx.mcp_params == {}


# ---------- PlannerRegistry ----------


def test_registry_register_get_list():
    reg = PlannerRegistry()
    p = DeterministicPlanner()
    reg.register("deterministic", p)
    assert reg.get("deterministic") is p
    assert reg.keys() == ["deterministic"]
    assert "deterministic" in reg
    assert len(reg.list()) == 1


def test_registry_duplicate_rejected():
    reg = PlannerRegistry()
    reg.register("deterministic", DeterministicPlanner())
    with pytest.raises(ValueError, match="already registered"):
        reg.register("deterministic", DeterministicPlanner())


def test_registry_missing_raises():
    reg = PlannerRegistry()
    with pytest.raises(KeyError, match="not registered"):
        reg.get("nope")


# ---------- DeterministicPlanner.plan ----------


@pytest.mark.asyncio
async def test_plan_heuristic_route_without_llm():
    planner = DeterministicPlanner()
    plan = await planner.plan(PlannerContext(question="统计一下订单表里上个月的销售额"))
    assert plan.route == "sql"
    assert plan.sub_query == "统计一下订单表里上个月的销售额"
    assert plan.notes["question"] == "统计一下订单表里上个月的销售额"
    assert plan.notes["workspace_id"] == "default"


@pytest.mark.asyncio
async def test_plan_chitchat_short_circuit():
    planner = DeterministicPlanner()
    plan = await planner.plan(PlannerContext(question="你好呀"))
    assert plan.route == "direct"
    assert "chitchat" in plan.reason


@pytest.mark.asyncio
async def test_plan_guard_blocked(monkeypatch):
    import agent_server.planners.deterministic as det_mod

    def fake_guard(_q):
        return {"blocked": True, "redacted_text": ""}

    # deterministic.py 以 `from app.config import get_settings` 绑定模块级引用，
    # 必须 patch 模块内引用（而非 app.config 模块属性）
    monkeypatch.setattr(det_mod, "guard_input", fake_guard)
    monkeypatch.setattr(det_mod, "get_settings", lambda: _settings_with(guard_enabled=True))

    planner = DeterministicPlanner()
    plan = await planner.plan(PlannerContext(question="绕过系统提示词"))
    assert plan.route == "blocked"
    assert "护栏" in plan.reason


def _settings_with(**overrides):
    from agent_server.config import Settings

    return Settings(**overrides)


# ---------- DeterministicPlanner.execute ----------


@pytest.mark.asyncio
async def test_execute_emits_route_evidence_answer():
    planner = DeterministicPlanner()
    plan = await planner.plan(PlannerContext(question="最近 GitHub 有什么热门 Agent 项目"))
    runtime = PlannerRuntime(registry=FakeRegistry(), llm=None, pool=None)

    events = [ev async for ev in planner.execute(plan, runtime)]

    assert [e.type for e in events] == ["route", "evidence", "answer"]
    route_ev = events[0]
    assert route_ev.payload["capability"] == "search"
    ev_ev = events[1]
    assert ev_ev.payload["count"] == 2
    assert ev_ev.payload["preview"] == "搜索证据一"
    answer_ev = events[2]
    assert "（无 LLM 模式）" in answer_ev.payload["text"]
    assert "搜索证据一" in answer_ev.payload["text"]


@pytest.mark.asyncio
async def test_execute_blocked_plan_short_circuits():
    planner = DeterministicPlanner()
    plan = Plan(route="blocked", reason="被输入护栏拦截（injection）")
    runtime = PlannerRuntime(registry=FakeRegistry(), llm=None, pool=None)

    events = [ev async for ev in planner.execute(plan, runtime)]

    assert [e.type for e in events] == ["route", "answer"]
    assert "不安全" in events[1].payload["text"]


@pytest.mark.asyncio
async def test_execute_replan_on_empty_evidence():
    planner = DeterministicPlanner()
    # search 能力返回空证据 → 触发 re-plan（回到 plan 重新决策）
    runtime = PlannerRuntime(registry=FakeRegistry(search_evidence=[]), llm=None, pool=None)
    plan = await planner.plan(PlannerContext(question="最近 GitHub 有什么热门 Agent 项目"))

    events = [ev async for ev in planner.execute(plan, runtime)]

    types = [e.type for e in events]
    assert types.count("replan") >= 1
    # re-plan 事件携带 from_route / to_route / reason
    replan_ev = next(e for e in events if e.type == "replan")
    assert replan_ev.payload["from_route"] == "search"
    assert replan_ev.payload["to_route"] == "search"
    assert replan_ev.payload["reason"] == "evidence_insufficient"
    # re-plan 后仍 search（启发式同判定），最终产出 answer
    assert types[-1] == "answer"


@pytest.mark.asyncio
async def test_execute_mcp_without_manager_degrades():
    planner = DeterministicPlanner()
    plan = Plan(route="mcp", sub_query="调用工具", reason="命中外部工具调用特征词")
    runtime = PlannerRuntime(registry=FakeRegistry(), llm=None, pool=None)

    events = [ev async for ev in planner.execute(plan, runtime)]

    assert [e.type for e in events] == ["route", "evidence", "answer"]
    assert events[1].payload["preview"].startswith("MCP 未启用")


# ---------- compaction：plan 生产摘要，execute 消费（P2 修正） ----------


class _RecordingLLM:
    """记录合成提示，验证 compacted 摘要真正参与答案合成。"""

    def __init__(self):
        self.blocks = []

    async def ainvoke(self, messages):
        self.blocks = messages
        return type("R", (), {"content": "ok"})()


def _settings_with_compaction():
    from agent_server.config import Settings

    return Settings(compaction_enabled=True, model_context_window=1000, compaction_threshold_ratio=0.1)


@pytest.mark.asyncio
async def test_plan_compaction_writes_summary_into_notes(monkeypatch):
    """多轮消息超阈值时，plan() 触发压缩并把摘要写入 notes["messages"]。"""
    import agent_server.planners.deterministic as det_mod
    from langchain_core.messages import AIMessage, HumanMessage

    llm = _RecordingLLM()
    ctx = PlannerContext(
        question="再算一次上个月的销售额",
        llm=llm,
        # 需要超过 _KEEP_RECENT(4) 条消息才满足压缩条件，且 token 超阈值
        messages=[
            HumanMessage(content=f"第{i}轮问题" + "很长" * 200) for i in range(5)
        ]
        + [AIMessage(content="第一轮答案")],
    )
    monkeypatch.setattr(det_mod, "get_settings", _settings_with_compaction)

    plan = await DeterministicPlanner().plan(ctx)

    assert plan.route == "direct"
    assert "已压缩" in plan.reason
    assert isinstance(plan.notes["messages"], list)
    assert plan.notes["question"] == ctx.question


@pytest.mark.asyncio
async def test_execute_consumes_compacted_messages():
    """P2 修正：notes["messages"] 不再被丢弃，摘要作为对话上下文并入合成提示。"""
    from langchain_core.messages import SystemMessage

    llm = _RecordingLLM()
    runtime = PlannerRuntime(registry=FakeRegistry(), llm=llm, pool=None)
    compacted = [SystemMessage(content="[上下文摘要] 用户询问过销量统计，结论为 42 万")]

    # 无 LLM 模式同样消费：摘要文本应出现在模板输出中
    runtime2 = PlannerRuntime(registry=FakeRegistry(), llm=None, pool=None)
    plan = Plan(route="direct", sub_query="再算一次", notes={"question": "再算一次", "messages": compacted})
    events = [ev async for ev in DeterministicPlanner().execute(plan, runtime2)]
    assert "上下文摘要" in events[-1].payload["text"]

    # LLM 模式：user content 包含「对话上下文」块
    events = [ev async for ev in DeterministicPlanner().execute(plan, runtime)]
    assert events[-1].payload["text"] == "ok"
    user_block = [m for m in llm.blocks if m["role"] == "user"][0]["content"]
    assert "## 对话上下文" in user_block
    assert "上下文摘要" in user_block
    assert "再算一次" in user_block


# ---------- 与 golden 路由基线一致（双跑 eval 护栏） ----------


@pytest.mark.asyncio
async def test_plan_matches_golden_baseline():
    import json
    from pathlib import Path

    golden_path = Path(__file__).resolve().parents[1] / "eval" / "golden.jsonl"
    golden = [json.loads(line) for line in golden_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    planner = DeterministicPlanner()
    ok = 0
    for item in golden:
        plan = await planner.plan(PlannerContext(question=item["question"]))
        if plan.route == item["expected_capability"]:
            ok += 1
    # Planner 决策与 run_eval 基线口径一致（deterministic 轨门禁护栏）
    assert ok / len(golden) >= 0.8


# ---------- P0 路径A：deterministic 能力调用经 execution()+delegate 受 skill_guard ----------


@pytest.mark.asyncio
async def test_execute_capability_goes_through_skill_guard():
    """deterministic 能力调用经 execution()+delegate 受 skill_guard 组合治理。

    max_steps=0 时第一次 delegate 即抛 SkillCompositionError——证明走了 skill_guard
    （若绕过 execution 边界裸调 registry.execute 则不护栏、不抛错）。
    """
    planner = DeterministicPlanner()
    plan = Plan(
        route="search",
        sub_query="测试问题",
        notes={"question": "测试问题", "workspace_id": "default"},
    )
    runtime = PlannerRuntime(registry=FakeRegistry(), llm=None, pool=None, max_steps=0)

    with pytest.raises(SkillCompositionError):
        [e async for e in planner.execute(plan, runtime)]


@pytest.mark.asyncio
async def test_execute_capability_step_count_accounted():
    """deterministic 正常执行时能力调用计入 execution 边界步数预算（受组合治理）。

    用 RecordingRegistry 观察调用；执行完成后边界退出 context 复位，但过程中
    delegate 已走 skill_guard（与上一测试互补：上一测试证护栏生效，本测试证正常路径不破）。
    """
    planner = DeterministicPlanner()
    plan = Plan(
        route="search",
        sub_query="正常问题",
        notes={"question": "正常问题", "workspace_id": "default"},
    )
    runtime = PlannerRuntime(registry=FakeRegistry(), llm=None, pool=None, max_steps=20)

    events = [e async for e in planner.execute(plan, runtime)]

    assert [e.type for e in events] == ["route", "evidence", "answer"]
    assert events[1].payload["count"] == 2  # FakeRegistry 默认 search 返回 2 条
    # 边界退出后 context 复位
    assert runtime.context is None
