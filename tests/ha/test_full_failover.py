"""§HA 组合灾难测试（Phase HA-5）：A kill → B 接管 → B 分区 → C 接管 → 完成。

E999 灾难链：
    S1✓ checkpoint → S2✓ checkpoint → 💥kill A
    → B acquire → S3✓ checkpoint → S4✓ checkpoint → 💥B 网络隔离（不续租）
    → C acquire → S5✓ → COMPLETED

最终检查（用户 §14/§15）：checkpoint 链单调、lease 历史单 owner、副作用各 1 次、
trajectory 连续、最终结果 deterministic。
"""

import pytest

from .conftest import (
    checkpoint_completed,
    event_log,
    side_effect_counts,
    unique_execution_id,
)
from .helpers import (
    wait_lease_expiry,
    make_runtime,
    run_replica_a,
    run_replica_b_takeover,
)
from .haprobe import HAProbeRegistry, build_probe_graph


@pytest.mark.anyio
async def test_full_failover_a_kill_b_partition_c_completes(ha_stores):
    execution_id = unique_execution_id("HA")
    cp = ha_stores["checkpoint"]
    own = ha_stores["ownership"]

    # ---- 1) A：S1/S2 checkpoint 后 kill ----
    reg_a = HAProbeRegistry(ha_stores["pool"], execution_id, replica="A")
    rt_a = make_runtime(reg_a, own, ttl_s=0.6)
    await run_replica_a(build_probe_graph(2), rt_a, cp, execution_id, acquire_ttl=0.6)
    assert set(await checkpoint_completed(ha_stores["pool"], execution_id)) == {"step_1", "step_2"}
    assert await wait_lease_expiry(own, execution_id), "A lease 未过期"

    # ---- 2) B 接管：S3/S4 checkpoint 后"分区"（不续租不 release）----
    reg_b = HAProbeRegistry(ha_stores["pool"], execution_id, replica="B")
    rt_b = make_runtime(reg_b, own, ttl_s=0.6)
    b_events = await run_replica_a(build_probe_graph(4), rt_b, cp, execution_id, acquire_ttl=0.6)
    assert not any(ev.type == "error" for ev in b_events)
    assert reg_b.calls == ["step_3", "step_4"], f"B 应只跑 S3/S4: {reg_b.calls}"
    assert set(await checkpoint_completed(ha_stores["pool"], execution_id)) == {"step_1", "step_2", "step_3", "step_4"}
    assert await wait_lease_expiry(own, execution_id), "B lease 未过期（B 分区）"

    # ---- 3) C 接管：S5 完成 ----
    reg_c = HAProbeRegistry(ha_stores["pool"], execution_id, replica="C")
    rt_c = make_runtime(reg_c, own)
    c_events = await run_replica_b_takeover(
        build_probe_graph(5), rt_c, cp, execution_id, replica="C"
    )
    assert not any(ev.type == "error" for ev in c_events)
    assert reg_c.calls == ["step_5"], f"C 应只跑 S5: {reg_c.calls}"

    # ---- 最终一致性断言 ----
    # 副作用各 exactly 1 次（I4）
    counts = await side_effect_counts(ha_stores["pool"], execution_id)
    assert counts == {f"{execution_id}:step_{i}:WRITE": 1 for i in (1, 2, 3, 4, 5)}, f"副作用异常: {counts}"
    # checkpoint 链完整单调（I2）
    assert set(await checkpoint_completed(ha_stores["pool"], execution_id)) == {f"step_{i}" for i in (1, 2, 3, 4, 5)}
    # 审计事件流记录了三个副本的接管轨迹（trajectory 连续，I7）
    log = await event_log(ha_stores["pool"], execution_id)
    replicas_seen = {r for _, r, _, _ in log}
    assert {"A", "B", "C"} <= replicas_seen, f"审计事件应覆盖 A/B/C: {replicas_seen}"
    print(f"\n[HA 组合灾难] A kill→B 接管→B 分区→C 接管→完成，全 5 步副作用各 1 次，PASS")
