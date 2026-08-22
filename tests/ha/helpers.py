"""HA 场景公共辅助：驱动「A kill → B 接管 resume」的统一流程。

关键：不依赖 InMemory 的假时间，完全用 PG 的 expires_at 时间语义——
A 手动 acquire 短 ttl lease，跑完部分节点后「不续租、不 release」（等价 SIGKILL，
heartbeat 死亡），靠 PG 使 lease 过期，B 再 acquire 接管。
"""

import asyncio

from agent_runtime.planner.execution_graph import _run_graph_in_place
from agent_runtime.planner.protocol import PlannerRuntime

from .haprobe import HAProbeRegistry, build_probe_graph


def make_runtime(registry, ownership_store, *, ttl_s: float = 5.0) -> PlannerRuntime:
    return PlannerRuntime(
        registry,
        ownership_store=ownership_store,
        max_duration_seconds=ttl_s,
        max_steps=100,
        max_skill_depth=20,
    )


async def run_replica_a(
    graph, runtime, checkpoint_store, execution_id, *,
    acquire_ttl: float = 0.6, owner: str = "replica-A", fault_injector=None,
):
    """副本执行：手动 acquire lease（短 ttl）→ 跑节点写 checkpoint → 不续租即停（模拟 kill）。

    - 支持 FaultInjector：监听 evidence（checkpoint 已落盘）事件，到达注入点即停止副本
      （不续租、不 release → 靠 PG expires_at 使 lease 过期），模拟 kill/分区。
    - ``owner`` 可指定副本标识（A/B/C），使 lease 归属清晰。
    - 不 release、不续租 → 等价 SIGKILL 前 heartbeat 已死。
    """
    ok = await runtime.ownership_store.acquire(execution_id, owner, acquire_ttl)
    assert ok, f"{owner} acquire 失败（被他人持有？）execution={execution_id}"
    events = []
    async for ev in _run_graph_in_place(
        graph, runtime, checkpoint_store=checkpoint_store, execution_id=execution_id
    ):
        events.append(ev)
        # evidence 事件：本节点已执行 + checkpoint 已落盘 → 可注入故障
        if ev.type == "evidence" and fault_injector is not None:
            step_id = ev.payload.get("node")
            stop, _fault = fault_injector.should_stop(step_id)
            if stop:
                break
    # 不 release、不续租 → 模拟 SIGKILL / 网络分区
    return events


async def wait_lease_expiry(ownership_store, execution_id, timeout_s: float = 5.0):
    """等待 lease 过期（poll get_owner 返回 None）。"""
    t0 = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - t0 < timeout_s:
        if await ownership_store.get_owner(execution_id) is None:
            return True
        await asyncio.sleep(0.05)
    return False


async def run_replica_b_takeover(graph, runtime, checkpoint_store, execution_id, replica="B"):
    """B 副本：execute_graph 边界内 acquire（A lease 已过期）→ resume，从 checkpoint 继续。"""
    events = []
    async with runtime.execution(execution_id=execution_id):
        async for ev in _run_graph_in_place(
            graph, runtime, checkpoint_store=checkpoint_store, execution_id=execution_id
        ):
            events.append(ev)
    return events
