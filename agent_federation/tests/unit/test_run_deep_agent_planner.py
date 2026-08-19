"""run_deep_agent 经 Planner 协议 + PlannerRuntime 治理驱动（Plan-F Phase 3 联邦侧闭环）。

验证：run_deep_agent 主链路经 AgenticPlanner.arun 执行（而非裸调 _execute_agent_core），
且 guard/intent/cache/memory/monitor 副作用链保留、最终答案经 monitor.report_task_result 上报。
重型依赖（deepagents / subagents / 真实 LLM）全部 mock，仅测新接线点。
"""

from __future__ import annotations

import os

# 确保 agent.llm 模块在 import main_agent 时成功初始化（无真实 key 时的测试桩）
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("OPENAI_BASE_URL", "http://localhost/v1")

import pytest
from agent_federation.planners import AgenticPlanner


@pytest.mark.asyncio
async def test_run_deep_agent_uses_planner_arun(monkeypatch):
    import agent_federation.agent.main_agent as ma

    # 隔离所有外部副作用：直接回答案，不做真实执行/记忆/缓存/意图判别
    monkeypatch.setattr(ma, "_execute_agent_core", lambda q, w, m=None: _await("上海共有 128 个用户。"))
    monkeypatch.setattr(ma, "get_main_agent", lambda *a, **k: _await("AGENT"))
    monkeypatch.setattr(ma, "remember_episodic", lambda *a, **k: _await(None))

    # spy：确认经 AgenticPlanner.arun 走通，而非裸调 _execute_agent_core
    calls = []
    real_arun = AgenticPlanner.arun

    async def spy_arun(self, question, workspace_id, runtime, main_agent=None):
        calls.append((question, workspace_id, main_agent))
        return await real_arun(self, question, workspace_id, runtime, main_agent)

    monkeypatch.setattr(AgenticPlanner, "arun", spy_arun)

    # spy monitor 上报
    reported = []
    monkeypatch.setattr(ma.monitor, "report_task_result", lambda ans: reported.append(ans))

    # 关闭所有可选阶段开关，走最简链路
    for flag in ("GUARD_ENABLED", "INTENT_ENABLED", "CACHE_ENABLED", "DYNAMIC_AGENT_ENABLED"):
        monkeypatch.setenv(flag, "false")

    await ma.run_deep_agent("帮我查一下上海的用户", "ws1")

    # 经 planner.arun 调用一次，参数透传正确
    assert len(calls) == 1
    assert calls[0][0] == "帮我查一下上海的用户"
    assert calls[0][1] == "ws1"
    # 收尾 monitor 上报最终答案（副作用链保留）
    assert reported and reported[-1] == "上海共有 128 个用户。"


async def _await(value):
    return value
