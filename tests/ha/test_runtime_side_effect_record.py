"""§HA H2 验收：运行时副作用落库真正生效（effectively-once 证据闭环）。

P0 阶段 side_effects 表的唯一约束只在测试桩（HAProbeRegistry.execute 直接写 DB）
中被验证，运行时代码从未调用它。H2 把落库从测试桩移到运行时
（execution_graph._run 在 delegate 成功后调 runtime.side_effect_store.record），
使 effectively-once 从「测试自证」变为「运行时真保证」。

本测试断言：
1. runtime.side_effect_store 注入后，execute_graph 跑完每个成功 step 都会落一条
   effect_key=execution_id:step_id:skill:<name> 的记录到 PG（运行时真落库）。
2. PgSideEffectStore.record 对同一 effect_key 幂等：重复写返回 False，DB 仍只 1 条。
3. PgSideEffectStore.has 能查到已落地 step（B 接管 resume 时据此判断是否跳过重跑）。

注意：HAProbeRegistry 自身也会写 effect_type=WRITE 的桩记录，本测试只校验由
运行时落库的 skill:* 类型记录，与桩记录互不冲突、各计各的。
"""

import pytest

from agent_runtime.planner.durability_pg import PgSideEffectStore
from agent_runtime.planner.execution_graph import execute_graph
from agent_runtime.planner.protocol import PlannerRuntime

from .conftest import side_effect_counts, unique_execution_id
from .haprobe import HAProbeRegistry, build_probe_graph
from .helpers import make_runtime


def _make_runtime_with_side_effects(registry, ownership_store, side_effect_store, *, ttl_s=5.0):
    return PlannerRuntime(
        registry,
        ownership_store=ownership_store,
        side_effect_store=side_effect_store,
        max_duration_seconds=ttl_s,
        max_steps=100,
        max_skill_depth=20,
    )


async def test_runtime_records_side_effects_on_delegate_success(pg_pool, ha_stores):
    """运行时 execute_graph 每完成一个 step，side_effect_store 都落一条 skill:* 记录。"""
    execution_id = unique_execution_id("H2")
    n_steps = 4
    graph = build_probe_graph(n_steps)
    registry = HAProbeRegistry(pg_pool, execution_id, sleep_s=0.02, replica="A")

    runtime = _make_runtime_with_side_effects(
        registry, ha_stores["ownership"], ha_stores["side_effect"]
    )
    # execute_graph 内部已创建 execution() 边界（含 acquire lease），不要在外层再包一次，
    # 否则嵌套 execution() 会二次 acquire 同 eid（新 owner）触发 ExecutionNotOwned。
    async for _ev in execute_graph(graph, runtime, execution_id=execution_id):
        pass

    # 仅校验运行时落库的 skill:* 类型记录
    counts = await side_effect_counts(pg_pool, execution_id)
    skill_keys = [k for k in counts if ":skill:" in k]
    assert len(skill_keys) == n_steps, f"运行时应落 {n_steps} 条 skill 记录，实际 {len(skill_keys)}: {skill_keys}"
    # 每条恰好 1 次（幂等：首次成功写入，无重复 attempt）
    assert all(counts[k] == 1 for k in skill_keys), (
        f"每条 skill 记录应恰好 1 次: {counts}"
    )


async def test_side_effect_record_is_idempotent(pg_pool, ha_stores):
    """PgSideEffectStore.record 对同一 effect_key 重复写返回 False，DB 仍只 1 条。"""
    execution_id = unique_execution_id("H2-IDEM")
    store = PgSideEffectStore(pg_pool)
    first = await store.record(execution_id, "step_1", "skill:step_1", "replica-A:abc")
    second = await store.record(execution_id, "step_1", "skill:step_1", "replica-B:def")
    assert first is True, "首次 record 应返回 True（新写入）"
    assert second is False, "重复 effect_key 应幂等去重，返回 False"
    assert await store.has(execution_id, "step_1", "skill:step_1") is True
    counts = await side_effect_counts(pg_pool, execution_id)
    skill_keys = [k for k in counts if ":skill:" in k]
    assert len(skill_keys) == 1 and counts[skill_keys[0]] == 1, f"幂等后仅 1 条: {counts}"


async def test_resume_sees_prior_side_effects(pg_pool, ha_stores):
    """B 接管时能通过 side_effect_store.has 判断哪些 step 副作用已落地（resume 依据）。"""
    execution_id = unique_execution_id("H2-RESUME")
    store = PgSideEffectStore(pg_pool)
    # 模拟 A 已落 step_1 / step_2 的副作用（effectively-once 已发生）
    await store.record(execution_id, "step_1", "skill:step_1", "replica-A:x")
    await store.record(execution_id, "step_2", "skill:step_2", "replica-A:x")
    # B 接管查询：已落地 = True，未落地 = False
    assert await store.has(execution_id, "step_1", "skill:step_1") is True
    assert await store.has(execution_id, "step_2", "skill:step_2") is True
    assert await store.has(execution_id, "step_3", "skill:step_3") is False
