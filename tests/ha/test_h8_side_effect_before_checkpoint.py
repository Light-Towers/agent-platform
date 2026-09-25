"""§HA-I8：kill in side-effect/checkpoint window —— 最危险的双写窗口（用户 §14）。

场景：
A 真实执行：
  step_1 → 写 side_effect_1 → 写 checkpoint_1
  step_2 → 写 side_effect_2 ✔  → 【此处被杀，checkpoint_2 未落】

B 接管（从 checkpoint_1 resume）：
  step_2 → 重跑：side_effect_2 已存在（唯一约束冲突）→ 跳过实际效果
  step_2 → 写 checkpoint_2

验证点（effectively-once 证据）：
- step_2 execution attempts ≥ 2（A 一次 + B 一次）
- step_2 actual side effects = 1（idempotency 兜底）
- 最终 checkpoint 完整（step_1, step_2 均 completed）

这证明：即便崩溃发生在「真实副作用已落、checkpoint 未写」的最危险窗口，
当前 side_effects 设计在 probe 模型下仍能把最终业务副作用收敛为 effectively-once。
（注意：H3 边界——若真实业务副作用本身不支持幂等，则此处仍会 ×2；probe 模型
依赖 side_effects 唯一约束做幂等兜底，即「业务副作用 = INSERT 唯一约束」时成立。）
"""

import pytest

from .conftest import (
    checkpoint_completed,
    side_effect_counts,
    unique_execution_id,
)
from .fault_injector import FaultInjector
from .haprobe import HAProbeRegistry, build_probe_graph
from .helpers import make_runtime, run_replica_a, run_replica_b_takeover, wait_lease_expiry


@pytest.mark.anyio
async def test_h8_kill_after_side_effect_before_checkpoint(ha_stores):
    execution_id = unique_execution_id("HA-I8")
    cp = ha_stores["checkpoint"]
    own = ha_stores["ownership"]

    # ---- A：真实执行 step_1（checkpoint1 + effect1），step_2 写完 effect2 即 kill（checkpoint2 未落）----
    fi = FaultInjector(kill_after_side_effect=["step_2"])
    reg_a = HAProbeRegistry(ha_stores["pool"], execution_id, replica="A", fault_injector=fi)
    rt_a = make_runtime(reg_a, own, ttl_s=0.6)
    await run_replica_a(
        build_probe_graph(2), rt_a, cp, execution_id,
        acquire_ttl=0.6, owner="replica-A", fault_injector=fi, registry=reg_a,
    )
    # step_1 已 checkpoint；step_2 的 side_effect 已落但 checkpoint_2 未写
    assert set(await checkpoint_completed(ha_stores["pool"], execution_id)) == {"step_1"}, \
        "step_2 不应出现在 checkpoint（被杀于 side_effect→checkpoint 窗口）"
    counts_pre = await side_effect_counts(ha_stores["pool"], execution_id)
    assert counts_pre == {f"{execution_id}:step_1:WRITE": 1, f"{execution_id}:step_2:WRITE": 1}, \
        f"side_effect 窗口前状态异常: {counts_pre}"

    # ---- 等 A lease 过期 ----
    assert await wait_lease_expiry(own, execution_id), "A lease 未过期"

    # ---- B 接管：从 checkpoint_1 resume，重跑 step_2 ----
    reg_b = HAProbeRegistry(ha_stores["pool"], execution_id, replica="B")
    rt_b = make_runtime(reg_b, own)
    b_events = await run_replica_b_takeover(
        build_probe_graph(2), rt_b, cp, execution_id, replica="B"
    )
    assert not any(ev.type == "error" for ev in b_events)
    # B 从 checkpoint_1 重跑 step_2（step_1 复用）
    assert reg_b.calls == ["step_2"], f"B 应从 step_2 开始: {reg_b.calls}"

    # ---- effectively-once：attempt≥2 但 effect 仍为 1 ----
    counts = await side_effect_counts(ha_stores["pool"], execution_id)
    assert counts == {f"{execution_id}:step_1:WRITE": 1, f"{execution_id}:step_2:WRITE": 1}, \
        f"最危险窗口后副作用异常（应恒=1）: {counts}"
    assert reg_b.actual_effects == [], \
        "B 重跑 step_2 时 side_effect 已被幂等跳过（唯一约束冲突），不应再次落库"

    # checkpoint 最终完整
    assert set(await checkpoint_completed(ha_stores["pool"], execution_id)) == {"step_1", "step_2"}
    print("\n[HA-I8] 最危险窗口（side_effect✔ → crash → checkpoint✘）：step_2 attempt≥2 但 effect=1，effectively-once 成立")
