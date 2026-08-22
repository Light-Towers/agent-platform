"""§HA 场景 7：重复提交同一个 execution（API idempotency + execution + side-effect）。

同一 execution_id 提交两次：第一次完成，第二次因 checkpoint 已完整而无新副作用。
验证「重复提交 → 副作用只发生一次」，把 API idempotency / execution idempotency /
side-effect idempotency 串起来（用户 §13）。
"""

import pytest

from .conftest import side_effect_counts, unique_execution_id
from .haprobe import HAProbeRegistry, build_probe_graph
from .helpers import make_runtime, run_replica_b_takeover
from agent_runtime.planner.execution_graph import _run_graph_in_place


@pytest.mark.anyio
async def test_duplicate_submit_effect_once(ha_stores):
    execution_id = unique_execution_id("HA")
    cp = ha_stores["checkpoint"]
    own = ha_stores["ownership"]

    # 第一次提交：A 完成全部 3 步
    reg_a = HAProbeRegistry(ha_stores["pool"], execution_id, replica="A")
    rt_a = make_runtime(reg_a, own)
    async with rt_a.execution(execution_id=execution_id):
        ev1 = [
            ev async for ev in _run_graph_in_place(
                build_probe_graph(3), rt_a, checkpoint_store=cp, execution_id=execution_id
            )
        ]
    assert not any(ev.type == "error" for ev in ev1)

    counts_after_first = await side_effect_counts(ha_stores["pool"], execution_id)
    assert counts_after_first == {f"{execution_id}:step_{i}:WRITE": 1 for i in (1, 2, 3)}

    # 第二次提交（重复，同 execution_id）：checkpoint 已完整，无新副作用
    reg_b = HAProbeRegistry(ha_stores["pool"], execution_id, replica="B")
    rt_b = make_runtime(reg_b, own)
    b_events = await run_replica_b_takeover(
        build_probe_graph(3), rt_b, cp, execution_id, replica="B"
    )
    # 全部节点复用，B 无实际调用
    assert reg_b.calls == [], f"重复提交不应重新执行: {reg_b.calls}"

    counts_after_second = await side_effect_counts(ha_stores["pool"], execution_id)
    assert counts_after_second == counts_after_first, "重复提交不应新增副作用"
    print(f"[HA 场景7] 重复提交同一 execution：副作用保持各 1 次，PASS")
