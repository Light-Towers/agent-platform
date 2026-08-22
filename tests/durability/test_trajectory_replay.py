"""P3-2 Trajectory Replay 验证。

覆盖：精确重放无 divergence；result_change / error_change / order / extra_call / missing_call
五类 divergence 检测；replay 复用 execute_plan 真实执行链。
"""

from __future__ import annotations

import pytest
from agent_runtime.trajectory import (
    ReplayRegistry,
    ReplayReport,
    TrajectoryRecord,
    TrajectoryStep,
    build_replay_registry,
    replay_trajectory,
)


def _record(result="golden") -> TrajectoryRecord:
    return TrajectoryRecord(
        session_id="s",
        planner="deterministic",
        plan={"mode": "deterministic", "route": "search", "sub_query": "q", "reason": "", "notes": {}, "graph": None},
        steps=[TrajectoryStep(name="search", args={"q": "x"}, result=result, tokens=4)],
    )


@pytest.mark.asyncio
async def test_replay_exact_no_divergence():
    record = _record()
    report = await replay_trajectory(record, build_replay_registry(record))
    assert isinstance(report, ReplayReport)
    assert report.diverged is False
    assert len(report.replay_steps) == 1
    assert report.replay_steps[0].name == "search"
    assert report.replay_steps[0].result == "golden"


@pytest.mark.asyncio
async def test_replay_result_change():
    record = _record("golden")

    class _Drift:
        async def execute(self, name, **kwargs):
            return "drifted"

    report = await replay_trajectory(record, _Drift())
    kinds = {d.kind for d in report.divergences}
    assert "result_change" in kinds
    assert report.diverged is True


@pytest.mark.asyncio
async def test_replay_error_change():
    record = _record("golden")

    class _NowFails:
        async def execute(self, name, **kwargs):
            raise RuntimeError("now broken")

    report = await replay_trajectory(record, _NowFails())
    kinds = {d.kind for d in report.divergences}
    assert "error_change" in kinds


@pytest.mark.asyncio
async def test_replay_missing_call():
    record = TrajectoryRecord(
        plan={"mode": "deterministic", "route": "search", "sub_query": "q", "reason": "", "notes": {}, "graph": None},
        steps=[
            TrajectoryStep(name="search", args={"q": "x"}, result="r1", tokens=4),
            TrajectoryStep(name="rag", args={"q": "x"}, result="r2", tokens=2),
        ],
    )

    # 只触发一次调用的当前注册表（少一步）→ missing_call
    class _OneShot:
        def __init__(self):
            self._n = 0

        async def execute(self, name, **kwargs):
            self._n += 1
            if self._n == 1:
                return "r1"
            raise AssertionError("unexpected second call")

    report = await replay_trajectory(record, _OneShot())
    kinds = {d.kind for d in report.divergences}
    assert "missing_call" in kinds


def test_replay_registry_order_and_extra():
    record = _record()
    reg = ReplayRegistry(record)
    # 序位 0 期望 search，实得 rag → order divergence
    import asyncio

    asyncio.run(reg.execute("rag", q="x"))
    # 超出录制步数 → extra_call 且抛错
    with pytest.raises(RuntimeError):
        asyncio.run(reg.execute("search", q="x"))
    kinds = {d.kind for d in reg.divergences}
    assert "order" in kinds
    assert "extra_call" in kinds
    assert reg.actual_steps[0].name == "rag"
