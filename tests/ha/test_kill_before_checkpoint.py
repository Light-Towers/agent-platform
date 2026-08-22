"""§HA 场景 3：kill before checkpoint —— 暴露 Durable Execution 的幂等语义。

A 执行 S1（checkpoint1），随后在 S2 产生了 side_effect 但 checkpoint2 尚未写入即被杀。
B 接管后「latest checkpoint = S1」，重跑 S2。

这不是失败，而是系统语义的证据——必须回答：V2 是 at-least-once 还是 effectively-once？
- S2 execution attempts ≥ 2（A 一次 + B 一次）
- S2 actual side effects = 1（idempotency 兜底）
=> effectively-once outcome（用户 §8/§9/§19 红线）
"""

import pytest

from .conftest import (
    checkpoint_completed,
    side_effect_counts,
    unique_execution_id,
)
from .helpers import wait_lease_expiry, make_runtime, run_replica_a, run_replica_b_takeover
from .haprobe import HAProbeRegistry, build_probe_graph


@pytest.mark.anyio
async def test_kill_before_checkpoint_effectively_once(ha_stores):
    execution_id = unique_execution_id("HA")
    cp = ha_stores["checkpoint"]
    own = ha_stores["ownership"]

    # ---- A：跑 S1（checkpoint1），然后在 S2 产生副作用但 checkpoint2 未写即"kill" ----
    reg_a = HAProbeRegistry(ha_stores["pool"], execution_id, replica="A")
    rt_a = make_runtime(reg_a, own, ttl_s=0.6)
    await run_replica_a(build_probe_graph(1), rt_a, cp, execution_id, acquire_ttl=0.6)
    # A 的 S1 已 checkpoint
    assert set(await checkpoint_completed(ha_stores["pool"], execution_id)) == {"step_1"}
    # 模拟 A 在 S2 产生了副作用（checkpoint2 未落盘）即被杀
    await reg_a.simulate_effect_without_checkpoint("step_2")

    # ---- 等 A lease 过期 ----
    assert await wait_lease_expiry(own, execution_id), "A lease 未过期"

    # ---- B 接管：从 checkpoint1 resume，重跑 S2（副作用被幂等跳过）----
    reg_b = HAProbeRegistry(ha_stores["pool"], execution_id, replica="B")
    rt_b = make_runtime(reg_b, own)
    b_events = await run_replica_b_takeover(
        build_probe_graph(2), rt_b, cp, execution_id, replica="B"
    )
    assert not any(ev.type == "error" for ev in b_events)
    # B 从 checkpoint1 重跑 S2（S1 复用）
    assert reg_b.calls == ["step_2"], f"B 应从 S2 开始: {reg_b.calls}"

    # ---- effectively-once：attempt≥2 但 effect=1 ----
    counts = await side_effect_counts(ha_stores["pool"], execution_id)
    assert counts == {f"{execution_id}:step_1:WRITE": 1, f"{execution_id}:step_2:WRITE": 1}, f"副作用异常: {counts}"
    assert reg_b.actual_effects == [], "B 重跑 S2 时副作用被幂等跳过（不应再次落库）"

    # checkpoint 完整
    assert set(await checkpoint_completed(ha_stores["pool"], execution_id)) == {"step_1", "step_2"}
    print(f"\n[HA 场景3] kill-before-checkpoint：S2 attempt≥2 但 actual effect=1，effectively-once 成立")
