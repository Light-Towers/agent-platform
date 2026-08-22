"""§HA 场景 1：最基础的 checkpoint recovery（不 kill）。

验证「checkpoint 本身真的在工作」：单副本跑完 3 步，checkpoint 记录 S1/S2/S3，
副作用各 1 次，trajectory 连续。这是 Phase HA-1 的地基。
"""

import pytest
from agent_runtime.planner.execution_graph import _run_graph_in_place

from .conftest import checkpoint_completed, event_log, side_effect_counts, unique_execution_id
from .haprobe import HAProbeRegistry, build_probe_graph
from .helpers import make_runtime


@pytest.mark.anyio
async def test_checkpoint_persists_all_steps(ha_stores):
    execution_id = unique_execution_id("HA")
    registry = HAProbeRegistry(ha_stores["pool"], execution_id, replica="A")
    rt = make_runtime(registry, ha_stores["ownership"])
    graph = build_probe_graph(3)  # S1 → S2 → S3

    async with rt.execution(execution_id=execution_id):
        events = [
            ev async for ev in _run_graph_in_place(
                graph, rt, checkpoint_store=ha_stores["checkpoint"], execution_id=execution_id
            )
        ]

    # I2 单调：checkpoint 记录了全部 3 步
    completed = await checkpoint_completed(ha_stores["pool"], execution_id)
    assert set(completed) == {"step_1", "step_2", "step_3"}, f"checkpoint 缺步: {completed}"
    # I4 副作用不重复：3 步各 1 次
    counts = await side_effect_counts(ha_stores["pool"], execution_id)
    assert counts == {f"{execution_id}:step_{i}:WRITE": 1 for i in (1, 2, 3)}, f"副作用异常: {counts}"
    # trajectory 连续：3 个 step 事件 + 无 error
    assert not any(ev.type == "error" for ev in events)
    assert [ev.payload["node"] for ev in events if ev.type == "evidence"] == ["step_1", "step_2", "step_3"]
    # 审计事件流非空
    log = await event_log(ha_stores["pool"], execution_id)
    assert len(log) >= 3, "execution_events 应记录至少 3 条 step 事件"
