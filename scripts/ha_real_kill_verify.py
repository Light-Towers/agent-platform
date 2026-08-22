"""§HA H1 真端到端验证：双独立进程 + 真实 PostgreSQL + kill -9 接管。

弥补 tests/ha 用「手动 acquire 短 ttl 不 release」模拟 SIGKILL 的不足，本脚本起两个
真实的 OS 进程（agent-a / agent-b）共享本机 5433 的 PostgreSQL，对同一个 execution_id
做真 kill -9：

  1. 进程 A（replica=agent-a）跑 execute_graph（3 步，每步 sleep 留出故障窗），
     在步骤 1 完成后立刻 SIGKILL 自身（模拟副本崩溃 / OOMKill / pod eviction）
  2. A 的 PG lease 不会因 kill 释放，但 lease 有 TTL；A 死前若已落步骤 1 的 checkpoint，
     B 等 lease 过期后 acquire 成功，从 checkpoint 续跑剩余步骤
  3. 进程 B（replica=agent-b）对同一 execution_id execute_graph 接管

验收断言（effectively-once 证据）：
  - side_effects 中 :WRITE 类型每 step 恰好 1 条（HAProbe 桩幂等）
  - side_effects 中 :skill: 类型每 step 恰好 1 条（运行时 H2 落库，resume 不重跑已落地 step）
  - 任一 step 的 side effect 不重复 → 跨进程接管不引入重复副作用

前置：本机 PostgreSQL 监听 5433，凭证 agent/agent_platform_dev，库 agent_platform。
本脚本完全自包含（内联 HAProbe 注册表，不依赖 tests 包结构）。
用法：
  .venv/bin/python scripts/ha_real_kill_verify.py
"""

import asyncio
import multiprocessing
import os
import signal
import sys
import time

# 让脚本可直接从仓库根运行，导入 packages/agent-runtime 下的包
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "packages", "agent-runtime"))

PG_URL = os.environ.get(
    "AGENT_PLATFORM_PG_URL",
    "postgresql://agent:agent_platform_dev@localhost:5433/agent_platform",
)
STEPS = 3
STEP_SLEEP = 1.5          # 每步 sleep，留出故障注入窗（3×1.5=4.5s < LEASE_TTL，B 可从容续跑）
LEASE_TTL = 8.0           # 副本 lease TTL，B 需等 A 的 lease 过期才能接管
MODE = os.environ.get("HA_MODE", "run")   # run | a | b


# ---- 内联 HAProbe 设施（自包含，不依赖 tests 包结构）----

class HAProbeRegistry:
    """注册表：registry.execute(name, ...) 契约；name 形如 step_1/step_2/...。

    每个 step 先写 side_effects（幂等：effect_key 唯一约束冲突 → 跳过实际效果），
    再 sleep 留出故障注入窗，返回结果。
    """

    def __init__(self, pool, execution_id: str, *, sleep_s: float = 0.05, replica: str = "A"):
        self._pool = pool
        self._execution_id = execution_id
        self._sleep_s = sleep_s
        self._replica = replica
        self.calls: list[str] = []
        self.actual_effects: list[str] = []

    def assert_composition_valid(self) -> None:
        return None

    async def execute(self, name: str, **kwargs) -> str:
        import json
        self.calls.append(name)
        step_id = name
        effect_key = f"{self._execution_id}:{step_id}:WRITE"
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO side_effects (effect_key, execution_id, attempt_id, step_id, effect_type, owner) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (effect_key) DO NOTHING RETURNING effect_key",
                (effect_key, self._execution_id, f"{self._replica}-{step_id}", step_id, "WRITE", self._replica),
            )
            inserted = await cur.fetchone()
        effect_occurred = "yes" if inserted else "skipped-duplicate"
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO execution_events (execution_id, attempt_id, replica, event, step_id) "
                "VALUES (%s, %s, %s, %s, %s)",
                (self._execution_id, f"{self._replica}-{step_id}", self._replica,
                 f"STEP_EXECUTED (effect={effect_occurred})", step_id),
            )
        if self._sleep_s:
            await asyncio.sleep(self._sleep_s)
        return json.dumps({"step": step_id, "effect": effect_occurred})


def build_probe_graph(n_steps: int):
    """构建 N 步顺序 DAG：step_1 → step_2 → ... → step_N。"""
    from agent_runtime.planner.execution_graph import ExecutionGraph
    g = ExecutionGraph()
    for i in range(1, n_steps + 1):
        g.add_node(f"step_{i}", f"step_{i}")
        if i > 1:
            g.add_edge(f"step_{i}", f"step_{i-1}")
    return g


async def _clean_execution(pool, execution_id: str):
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM side_effects WHERE execution_id = %s", (execution_id,))
        await conn.execute("DELETE FROM execution_leases WHERE execution_id = %s", (execution_id,))
        await conn.execute("DELETE FROM execution_checkpoints WHERE execution_id = %s", (execution_id,))
        await conn.execute("DELETE FROM execution_events WHERE execution_id = %s", (execution_id,))


def _make_runtime(pool, registry, replica: str):
    from agent_runtime.planner.durability_pg import (
        PgCheckpointStore,
        PgExecutionOwnershipStore,
        PgSideEffectStore,
    )
    from agent_runtime.planner.protocol import PlannerRuntime
    return PlannerRuntime(
        registry,
        ownership_store=PgExecutionOwnershipStore(pool),
        checkpoint_store=PgCheckpointStore(pool),
        side_effect_store=PgSideEffectStore(pool),
        replica_id=replica,
        max_duration_seconds=LEASE_TTL,
        max_steps=100,
        max_skill_depth=20,
    )


def _proc_a(execution_id: str, ready_path: str):
    """进程 A：跑 execute_graph，步骤 1 完成后立刻 SIGKILL 自身（模拟副本崩溃）。"""
    async def _main():
        from agent_runtime import db as _db
        from agent_runtime.planner.execution_graph import execute_graph

        pool = await _db.init_pool(PG_URL)
        await _clean_execution(pool, execution_id)

        step_count = {"n": 0}

        class _KillAfterStep1(HAProbeRegistry):
            async def execute(self, name, **kw):
                res = await super().execute(name, **kw)
                step_count["n"] += 1
                if step_count["n"] == 1:
                    with open(ready_path, "w") as f:
                        f.write("ready")
                    os.kill(os.getpid(), signal.SIGKILL)
                return res

        registry = _KillAfterStep1(pool, execution_id, sleep_s=STEP_SLEEP, replica="agent-a")
        runtime = _make_runtime(pool, registry, "agent-a")
        async for _ev in execute_graph(build_probe_graph(STEPS), runtime, execution_id=execution_id):
            pass
        print(f"[agent-a] DONE (unexpected, should have been killed)", flush=True)

    asyncio.run(_main())


def _proc_b(execution_id: str):
    """进程 B：A 死、lease 过期后接管同 execution_id。"""
    async def _main():
        from agent_runtime import db as _db
        from agent_runtime.planner.execution_graph import execute_graph

        pool = await _db.init_pool(PG_URL)
        registry = HAProbeRegistry(pool, execution_id, sleep_s=STEP_SLEEP, replica="agent-b")
        runtime = _make_runtime(pool, registry, "agent-b")
        async for _ev in execute_graph(build_probe_graph(STEPS), runtime, execution_id=execution_id):
            pass
        print(f"[agent-b] DONE execution_id={execution_id}", flush=True)
        await _db.close_pool()
    asyncio.run(_main())


async def _assert_effectively_once(execution_id: str):
    from agent_runtime import db as _db
    pool = await _db.init_pool(PG_URL)
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT effect_key FROM side_effects WHERE execution_id = %s", (execution_id,)
        )
        rows = await cur.fetchall()
    await _db.close_pool()

    keys = [r[0] for r in rows]
    write_keys = [k for k in keys if ":WRITE" in k]
    skill_keys = [k for k in keys if ":skill:" in k]
    errors = []
    if len(write_keys) != STEPS:
        errors.append(f"WRITE 记录数应为 {STEPS}，实际 {len(write_keys)}: {write_keys}")
    if len(skill_keys) != STEPS:
        errors.append(f"skill 记录数应为 {STEPS}，实际 {len(skill_keys)}: {skill_keys}")
    if len(set(write_keys)) != len(write_keys):
        errors.append(f"WRITE 存在重复 effect_key（effectively-once 被破坏）: {write_keys}")
    if len(set(skill_keys)) != len(skill_keys):
        errors.append(f"skill 存在重复 effect_key（运行时落库幂等失败）: {skill_keys}")
    return errors, {"write": write_keys, "skill": skill_keys}


def main():
    execution_id = os.environ.get("HA_EXEC_ID", f"HA-REAL-{int(time.time())}")
    ready_path = os.path.join("/tmp", f"ha_ready_{execution_id}.txt")
    if os.path.exists(ready_path):
        os.remove(ready_path)

    if MODE == "a":
        _proc_a(execution_id, ready_path)
        return
    if MODE == "b":
        _proc_b(execution_id)
        return

    print(f"[main] execution_id={execution_id}", flush=True)
    pa = multiprocessing.Process(target=_proc_a, args=(execution_id, ready_path), name="agent-a")
    pa.start()
    for _ in range(120):
        if os.path.exists(ready_path):
            break
        time.sleep(0.25)
    else:
        print("[main] ERROR: A 未在预期时间内标记 ready（未触发自杀）", flush=True)
        pa.kill()
        sys.exit(2)
    print(f"[main] A 已自杀（SIGKILL）pid={pa.pid}", flush=True)
    pa.join(timeout=5)
    if pa.is_alive():
        pa.kill()

    wait = LEASE_TTL + 3.0
    print(f"[main] 等待 lease 过期 {wait}s 后启动 B 接管...", flush=True)
    time.sleep(wait)

    pb = multiprocessing.Process(target=_proc_b, args=(execution_id,), name="agent-b")
    pb.start()
    pb.join(timeout=60)
    if pb.is_alive():
        print("[main] ERROR: B 未在 60s 内完成接管", flush=True)
        pb.kill()
        sys.exit(3)

    errors, detail = asyncio.run(_assert_effectively_once(execution_id))
    print("[main] side_effects 明细:", detail, flush=True)
    if errors:
        print("[main] FAIL:", file=sys.stderr, flush=True)
        for e in errors:
            print("  -", e, file=sys.stderr, flush=True)
        sys.exit(1)
    print("[main] PASS: 跨进程 kill -9 接管验证通过（effectively-once 成立）", flush=True)


if __name__ == "__main__":
    main()
