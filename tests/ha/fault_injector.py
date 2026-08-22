"""FaultInjector（§HA 第 17 节）：可控故障注入器（harness 层，不侵入生产代码）。

驱动方式：harness 监听 _run_graph_in_place 的 evidence 事件流，当出现指定 step 的
完成事件（checkpoint 已落盘）时触发故障并停止副本（不续租、不 release → 靠 PG
expires_at 使 lease 过期），模拟 SIGKILL / OOMKill / pod eviction。

支持：
- kill_after_checkpoint: 在指定 step 的 checkpoint 落盘后"杀掉"副本
- partition_db: 在指定 step 后模拟网络分区（同样停止心跳 → lease 过期）

真实进程级故障仍建议 docker kill（更接近生产）；此处提供精细、可审计、可并行的注入。
"""


class FaultInjector:
    def __init__(self, *, kill_after_checkpoint: list[str] | None = None, partition_db: list[str] | None = None):
        self.kill_after_checkpoint = set(kill_after_checkpoint or [])
        self.partition_db = set(partition_db or [])
        self.events: list[tuple[str, str]] = []

    def should_stop(self, step_id: str) -> tuple[bool, str | None]:
        """在 step 的 checkpoint 落盘后（evidence 事件）调用。

        返回 (True, fault_name) 表示应在该 step 后注入故障并停止副本；(False, None) 继续。
        """
        if step_id in self.kill_after_checkpoint:
            self.events.append((step_id, "kill_after_checkpoint"))
            return True, "kill_after_checkpoint"
        if step_id in self.partition_db:
            self.events.append((step_id, "partition_db"))
            return True, "partition_db"
        return False, None

    def summary(self) -> str:
        return "; ".join(f"{s}:{a}" for s, a in self.events) or "no-fault-injected"
