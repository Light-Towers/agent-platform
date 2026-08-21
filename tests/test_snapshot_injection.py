# -*- coding: utf-8 -*-
"""WS-2：snapshot 消费闭环回归（第二轮 prompt 含上一轮 task 快照）。

验证：
- DeterministicPlanner.plan 把 PlannerContext.last_snapshot 透传到 plan.notes；
- _compose 经 render_snapshot_prompt 把任务状态结构化注入 prompt（无 LLM 模板路径）；
- 无快照时不注入（行为与改造前一致）。
"""

from __future__ import annotations

import pytest
from agent_runtime.planner.protocol import PlannerContext
from agent_server.planners.deterministic import DeterministicPlanner

_SNAPSHOT = {
    "task": {
        "goal": "分析销售数据",
        "completed_steps": ["fetch_data"],
        "pending": ["summarize"],
        "constraints": {},
    },
    "execution": {"outputs": {"sql": "ok"}, "errors": {}, "skill_stack": []},
}


@pytest.mark.asyncio
async def test_compose_injects_snapshot_block():
    planner = DeterministicPlanner()
    answer = await planner._compose(
        "继续分析", ["证据1"], [], llm=None, snapshot=_SNAPSHOT
    )
    assert "[上轮任务状态]" in answer
    assert "任务目标: 分析销售数据" in answer
    assert "已完成: fetch_data" in answer


@pytest.mark.asyncio
async def test_compose_without_snapshot_unchanged():
    planner = DeterministicPlanner()
    answer = await planner._compose("问题", ["证据1"], [], llm=None)
    assert "[上轮任务状态]" not in answer
    assert "证据1" in answer


@pytest.mark.asyncio
async def test_plan_carries_last_snapshot(monkeypatch):
    # 关闭护栏避免脱敏改写问题文本
    from agent_server.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "guard_enabled", False, raising=False)
    monkeypatch.setattr(settings, "compaction_enabled", False, raising=False)

    planner = DeterministicPlanner()
    ctx = PlannerContext(
        question="北京的天气怎么样",
        workspace_id="ws1",
        user_id="u1",
        llm=None,  # 路由回退启发式，无需 LLM
        last_snapshot=_SNAPSHOT,
    )
    plan = await planner.plan(ctx)
    assert plan.notes.get("last_snapshot") == _SNAPSHOT
