"""trajectory/replay 单元测试：ReplayRegistry 五类 divergence + replay_trajectory。"""

from __future__ import annotations

import pytest

from agent_runtime.trajectory.models import TrajectoryRecord, TrajectoryStep
from agent_runtime.trajectory.replay import (
    ReplayDivergence,
    build_replay_registry,
    replay_trajectory,
)


def _make_step(name="search", result="ok", error=None, index=0):
    return TrajectoryStep(name=name, args={}, result=result, error=error, index=index)


def _make_record(steps):
    return TrajectoryRecord(execution_id="test-exec", steps=steps, plan={"mode": "deterministic", "route": steps[0].name if steps else ""})


@pytest.mark.asyncio
async def test_replay_registry_exact_match():
    record = _make_record([_make_step("search", "result1", index=0)])
    reg = build_replay_registry(record)
    result = await reg.execute("search")
    assert result == "result1"
    assert len(reg.divergences) == 0


@pytest.mark.asyncio
async def test_replay_registry_order_mismatch():
    record = _make_record([_make_step("search", index=0)])
    reg = build_replay_registry(record)
    await reg.execute("different_skill")
    assert len(reg.divergences) == 1
    assert reg.divergences[0].kind == "order"


@pytest.mark.asyncio
async def test_replay_registry_extra_call():
    record = _make_record([_make_step("search", index=0)])
    reg = build_replay_registry(record)
    await reg.execute("search")
    with pytest.raises(RuntimeError, match="超出录制步数"):
        await reg.execute("extra_skill")
    assert any(d.kind == "extra_call" for d in reg.divergences)


@pytest.mark.asyncio
async def test_replay_registry_error_replay():
    record = _make_record([_make_step("search", error="timeout", index=0)])
    reg = build_replay_registry(record)
    with pytest.raises(RuntimeError, match="timeout"):
        await reg.execute("search")
    assert reg.actual_steps[0].error == "timeout"


@pytest.mark.asyncio
async def test_replay_trajectory_missing_call():
    record = _make_record([
        _make_step("search", "r1", index=0),
        _make_step("summarize", "r2", index=1),
    ])
    reg = build_replay_registry(record)
    report = await replay_trajectory(record, reg)
    assert report.diverged
    assert any(d.kind == "missing_call" for d in report.divergences)


@pytest.mark.asyncio
async def test_replay_trajectory_no_divergence():
    steps = [_make_step("search", "r1", index=0)]
    record = _make_record(steps)
    reg = build_replay_registry(record)
    report = await replay_trajectory(record, reg)
    assert not report.diverged
    assert len(report.replay_steps) == 1


@pytest.mark.asyncio
async def test_replay_trajectory_result_change():
    steps = [_make_step("search", "original_result", index=0)]
    record = _make_record(steps)

    class ModifiedRegistry:
        def __init__(self):
            self.divergences = []
            self._i = 0

        async def execute(self, name, **kwargs):
            self._i += 1
            return "different_result"

    report = await replay_trajectory(record, ModifiedRegistry())
    assert report.diverged
    assert any(d.kind == "result_change" for d in report.divergences)


@pytest.mark.asyncio
async def test_replay_trajectory_error_change():
    steps = [_make_step("search", "ok", error=None, index=0)]
    record = _make_record(steps)

    class FailingRegistry:
        def __init__(self):
            self.divergences = []

        async def execute(self, name, **kwargs):
            raise RuntimeError("now fails")

    report = await replay_trajectory(record, FailingRegistry())
    assert report.diverged
    assert any(d.kind == "error_change" for d in report.divergences)


def test_replay_divergence_to_dict():
    d = ReplayDivergence("order", 2, "detail text")
    assert d.to_dict() == {"kind": "order", "index": 2, "detail": "detail text"}
