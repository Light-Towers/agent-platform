"""HAProbeAgent：可控故障实验任务载体（§HA 第 4 节）。

每个 skill 对应一个 step，语义：
1. 执行（写 side_effect，幂等：effect_key 唯一约束冲突则跳过实际效果）
2. 写 checkpoint（由 _run_graph_in_place 每节点后持久化）
3. 记录 execution_events（可证明的 trajectory 审计流）
4. sleep（留出故障注入 / lease 时间窗）

副作用 effectively-once 证明：
- effect_key = execution_id + step_id + effect_type（唯一约束）
- 第一次执行：INSERT 成功 → 记录 actual_effect=1
- 第二次重跑（resume 或 kill-before-checkpoint 导致重复）：INSERT 冲突 → 跳过实际效果
- 故「execution attempts 可以 >1，但 actual side effects 恒 =1」
"""

import asyncio
import json

from agent_runtime.planner.execution_graph import ExecutionGraph

EFFECT_TYPES = ["WRITE", "MUTATE"]


class HAProbeRegistry:
    """注册表：registry.execute(name, ...) 契约；name 形如 step_1/step_2/..."""

    def __init__(self, pool, execution_id: str, *, sleep_s: float = 0.05, replica: str = "A", fault_injector=None):
        self._pool = pool
        self._execution_id = execution_id
        self._sleep_s = sleep_s
        self._replica = replica
        self._fault_injector = fault_injector
        # 内存记录（便于快速断言）
        self.calls: list[str] = []          # 每次实际调用的 step（attempt 可能重复）
        self.actual_effects: list[str] = [] # 真正落库的 side effect

    def assert_composition_valid(self) -> None:
        # 测试替身：不持有真实组合策略校验，按 execution() 契约提供 no-op 实现
        return None

    async def execute(self, name: str, **kwargs) -> str:
        self.calls.append(name)
        step_id = name  # step_1, step_2, ...
        effect_key = f"{self._execution_id}:{step_id}:WRITE"

        # 1) 写 side_effect（幂等）：唯一约束冲突 → 跳过实际效果（effectively-once）
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO side_effects (effect_key, execution_id, attempt_id, step_id, effect_type, owner) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (effect_key) DO NOTHING RETURNING effect_key",
                (effect_key, self._execution_id, f"A-{step_id}", step_id, "WRITE", self._replica),
            )
            inserted = await cur.fetchone()
        if inserted:
            self.actual_effects.append(step_id)
            effect_occurred = "yes"
        else:
            effect_occurred = "skipped-duplicate"

        # 2) 记录执行事件审计流
        await self._log_event(step_id, f"STEP_EXECUTED (effect={effect_occurred})")

        # 3) sleep 留出时间窗
        if self._sleep_s:
            await asyncio.sleep(self._sleep_s)
        return json.dumps({"step": step_id, "effect": effect_occurred})

    async def simulate_effect_without_checkpoint(self, step_id: str) -> None:
        """模拟「副作用已发生、但 checkpoint 尚未写入」的场景（kill before checkpoint）。

        等价于：A 在 step 执行中写了 side_effect，随即被 kill，checkpoint 未更新。
        这样 B resume 时从「上一个 checkpoint」重跑本 step，其 side_effect 会因唯一
        约束冲突被跳过 → 暴露 at-least-once(attempt>1) + effectively-once(effect=1) 语义。
        """
        effect_key = f"{self._execution_id}:{step_id}:WRITE"
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO side_effects (effect_key, execution_id, attempt_id, step_id, effect_type, owner) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (effect_key) DO NOTHING",
                (effect_key, self._execution_id, f"A-{step_id}-preckpt", step_id, "WRITE", self._replica),
            )

    async def _log_event(self, step_id: str | None, event: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO execution_events (execution_id, attempt_id, replica, event, step_id) "
                "VALUES (%s, %s, %s, %s, %s)",
                (self._execution_id, f"A-{step_id or 'init'}", self._replica, event, step_id),
            )


def build_probe_graph(n_steps: int) -> ExecutionGraph:
    """构建 N 步顺序 DAG：step_1 → step_2 → ... → step_N。"""
    g = ExecutionGraph()
    for i in range(1, n_steps + 1):
        g.add_node(f"step_{i}", f"step_{i}")
        if i > 1:
            g.add_edge(f"step_{i}", f"step_{i-1}")
    return g
