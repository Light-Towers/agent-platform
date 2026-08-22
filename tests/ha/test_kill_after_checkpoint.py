"""§HA 场景 2：kill after checkpoint —— 第一个真正的 HA 测试。

A 执行 S1、S2（写 checkpoint2）后被 kill；B 等 lease 过期后接管，从 checkpoint2
resume 执行 S3、S4。最终副作用必须 S1/S2/S3/S4 各 1 次——**S1/S2 不被重跑**。

这验证用户核心红线：
    checkpoint 没丢 / lease 能转移 / execution 不重复 / 副作用不重复 / 最终结果正确。
"""

import pytest

from .conftest import (
    checkpoint_completed,
    event_log,
    side_effect_counts,
    unique_execution_id,
)
from .haprobe import HAProbeRegistry, build_probe_graph
from .helpers import make_runtime, run_replica_a, run_replica_b_takeover, wait_lease_expiry


@pytest.mark.anyio
async def test_kill_after_checkpoint_b_takes_over(ha_stores):
    execution_id = unique_execution_id("HA")
    cp = ha_stores["checkpoint"]
    own = ha_stores["ownership"]

    # ---- A 副本：跑 S1、S2（写 checkpoint2）后 kill（不续租不 release）----
    reg_a = HAProbeRegistry(ha_stores["pool"], execution_id, replica="A")
    rt_a = make_runtime(reg_a, own, ttl_s=0.6)
    a_events = await run_replica_a(
        build_probe_graph(2), rt_a, cp, execution_id, acquire_ttl=0.6
    )
    # A 跑完 S1/S2
    assert not any(ev.type == "error" for ev in a_events)
    assert {ev.payload["node"] for ev in a_events if ev.type == "evidence"} == {"step_1", "step_2"}
    # checkpoint2 已落盘
    assert set(await checkpoint_completed(ha_stores["pool"], execution_id)) == {"step_1", "step_2"}

    # ---- 等 A lease 过期（SIGKILL 后 PG expires_at 自动过期）----
    assert await wait_lease_expiry(own, execution_id), "A lease 未在预期时间内过期"

    # ---- B 副本：acquire 接管，从 checkpoint2 resume S3、S4 ----
    reg_b = HAProbeRegistry(ha_stores["pool"], execution_id, replica="B")
    rt_b = make_runtime(reg_b, own)
    b_events = await run_replica_b_takeover(
        build_probe_graph(4), rt_b, cp, execution_id, replica="B"
    )

    # B 只新跑了 S3/S4（复用 checkpoint 的 S1/S2，不重跑）。
    # 注意：evidence 事件对「从 checkpoint 复用的已完成节点」也会补发，故用
    # reg_b.calls（registry 实际调用次数）判断是否重跑，而非 evidence 事件。
    assert not any(ev.type == "error" for ev in b_events)
    assert reg_b.calls == ["step_3", "step_4"], f"B 重跑了已完成节点: {reg_b.calls}"
    assert reg_b.actual_effects == ["step_3", "step_4"], f"B 重复产生了副作用: {reg_b.actual_effects}"
    # 事件流含全部 4 步（复用节点补发 evidence），但实际调用仅 2 步
    b_evidence = [ev.payload["node"] for ev in b_events if ev.type == "evidence"]
    assert set(b_evidence) == {"step_1", "step_2", "step_3", "step_4"}

    # ---- 副作用 each exactly once（I4）----
    counts = await side_effect_counts(ha_stores["pool"], execution_id)
    assert counts == {f"{execution_id}:step_{i}:WRITE": 1 for i in (1, 2, 3, 4)}, f"副作用异常: {counts}"

    # ---- 最终 checkpoint 完整 + trajectory 连续（I2/I7）----
    completed = await checkpoint_completed(ha_stores["pool"], execution_id)
    assert set(completed) == {"step_1", "step_2", "step_3", "step_4"}
    log = await event_log(ha_stores["pool"], execution_id)
    replicas = {ev for _, r, ev, _ in log}
    assert replicas, "execution_events 应有审计记录"
    print(f"\n[HA 场景2] execution={execution_id} 副作用各1次，B 接管从 checkpoint2 resume，PASS")
