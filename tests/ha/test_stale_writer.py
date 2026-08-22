"""§HA stale-writer fencing（P0 核心验收，用户要求的最关键测试）。

场景：A 丢 lease → B 接管 → A（zombie）故意晚写 checkpoint → A 写失败 → B 的
checkpoint 保持完整。

这是 Lease + Checkpoint + Recovery + Split-brain fencing 真正形成闭环的证据：
- A 的 completed={S1,S2}（version=2）
- B 接管后 completed={S1,S2,S3}（version=3）
- A 晚写旧 checkpoint（version=2 < 3）→ 被 PgCheckpointStore 的 monotonic CAS 拒绝
- 最终 checkpoint 仍为 {S1,S2,S3}，不被降级覆盖
"""

import pytest

from agent_runtime.planner.durability import Checkpoint, FencedWriteError

from .conftest import checkpoint_completed, side_effect_counts, unique_execution_id
from .helpers import (
    wait_lease_expiry,
    make_runtime,
    run_replica_a,
    run_replica_b_takeover,
)
from .haprobe import HAProbeRegistry, build_probe_graph


@pytest.mark.anyio
async def test_stale_writer_cannot_overwrite_new_checkpoint(ha_stores):
    execution_id = unique_execution_id("HA")
    cp = ha_stores["checkpoint"]
    own = ha_stores["ownership"]

    # ---- 1) A：跑 S1/S2，写 checkpoint version=2 ----
    reg_a = HAProbeRegistry(ha_stores["pool"], execution_id, replica="A")
    rt_a = make_runtime(reg_a, own, ttl_s=0.5)
    await run_replica_a(build_probe_graph(2), rt_a, cp, execution_id, acquire_ttl=0.5)
    assert set(await checkpoint_completed(ha_stores["pool"], execution_id)) == {"step_1", "step_2"}
    assert await wait_lease_expiry(own, execution_id), "A lease 未过期"

    # ---- 2) B 接管：resume S3，写 checkpoint version=3 ----
    reg_b = HAProbeRegistry(ha_stores["pool"], execution_id, replica="B")
    rt_b = make_runtime(reg_b, own)
    await run_replica_b_takeover(build_probe_graph(3), rt_b, cp, execution_id, replica="B")
    assert reg_b.calls == ["step_3"]
    assert set(await checkpoint_completed(ha_stores["pool"], execution_id)) == {"step_1", "step_2", "step_3"}

    # ---- 3) A（zombie）故意晚写旧 checkpoint（version=2 < 3）----
    stale_cp = Checkpoint(
        execution_id=execution_id,
        completed={"step_1": "out:step_1", "step_2": "out:step_2"},  # 旧结果，version=2
        resumable=False,
    )
    with pytest.raises(FencedWriteError):
        await cp.save(stale_cp)

    # ---- 4) B 的 checkpoint 必须保持（不被降级覆盖）----
    final = await checkpoint_completed(ha_stores["pool"], execution_id)
    assert set(final) == {"step_1", "step_2", "step_3"}, f"A 晚写覆盖了 B 的 checkpoint: {final}"

    # 副作用仍各 1 次（B 的 S3 + A 的 S1/S2，无重复）
    counts = await side_effect_counts(ha_stores["pool"], execution_id)
    assert counts == {f"{execution_id}:step_{i}:WRITE": 1 for i in (1, 2, 3)}, f"副作用异常: {counts}"

    print("\n[HA stale-writer] A 丢 lease 后晚写旧 checkpoint 被 FencedWriteError 拒绝，B checkpoint 保持，PASS")
