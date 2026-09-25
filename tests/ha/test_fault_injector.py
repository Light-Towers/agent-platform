"""§HA FaultInjector 验证：用注入器驱动「A kill_after_checkpoint=step_2 → B 接管」。

验证 FaultInjector 真正控制副本（不依赖手工 acquire_ttl），且副作用 effectively-once。
这是用户 §17 要求的故障注入器能力演示。
"""

import pytest

from .conftest import side_effect_counts, unique_execution_id
from .fault_injector import FaultInjector
from .haprobe import HAProbeRegistry, build_probe_graph
from .helpers import (
    make_runtime,
    run_replica_a,
    run_replica_b_takeover,
    wait_lease_expiry,
)


@pytest.mark.anyio
async def test_fault_injector_kill_after_checkpoint(ha_stores):
    execution_id = unique_execution_id("HA")
    cp = ha_stores["checkpoint"]
    own = ha_stores["ownership"]

    injector = FaultInjector(kill_after_checkpoint=["step_2"])

    # A：FaultInjector 在 step_2 checkpoint 落盘后 kill
    reg_a = HAProbeRegistry(ha_stores["pool"], execution_id, replica="A", fault_injector=injector)
    rt_a = make_runtime(reg_a, own, ttl_s=0.6)
    await run_replica_a(
        build_probe_graph(4), rt_a, cp, execution_id, acquire_ttl=0.6, owner="replica-A",
        fault_injector=injector,
    )
    assert reg_a.calls == ["step_1", "step_2"], f"FaultInjector 应在 step_2 后停止: {reg_a.calls}"
    assert injector.summary() == "step_2:kill_after_checkpoint", injector.summary()
    assert await wait_lease_expiry(own, execution_id), "A lease 未过期"

    # B 接管：从 checkpoint2 resume S3/S4
    reg_b = HAProbeRegistry(ha_stores["pool"], execution_id, replica="B")
    rt_b = make_runtime(reg_b, own)
    await run_replica_b_takeover(build_probe_graph(4), rt_b, cp, execution_id, replica="B")
    assert reg_b.calls == ["step_3", "step_4"], f"B 应只跑 S3/S4: {reg_b.calls}"

    counts = await side_effect_counts(ha_stores["pool"], execution_id)
    assert counts == {f"{execution_id}:step_{i}:WRITE": 1 for i in (1, 2, 3, 4)}, f"副作用异常: {counts}"
    print("\n[HA FaultInjector] kill_after_checkpoint=step_2 驱动 A→B 接管，副作用各 1 次，PASS")
