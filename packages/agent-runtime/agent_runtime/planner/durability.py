"""Durability（完整架构 Phase E）：执行级 checkpoint / resume（Runtime 能力，非 Planner 业务）。

架构契约（docs/complete-agent-runtime-architecture.md §11）：Durability 属于 Runtime，
而不是 Planner 的业务逻辑。``ExecutionGraph`` 执行时按节点落地 checkpoint，崩溃后可基于
同一 ``execution_id`` resume——已完成节点结果复用、未完成任务继续（尊重依赖边）。

本模块提供：
- ``CheckpointStore``：checkpoint 持久化契约（按 execution_id 读写已完成节点结果）；
- ``InMemoryCheckpointStore``：进程内默认实现（单进程 / 测试够用；多副本应注入 PG 实现）。
"""

from __future__ import annotations

import abc
import time
import uuid
from typing import Any


class FencedWriteError(RuntimeError):
    """分布式 fencing 失败：状态写操作携带的 generation token 已过期。

    说明当前持有该 execution 的 owner 已被新 owner（reaper claim 后 generation+1）
    取代；本次写操作因 ``WHERE generation=<stale_token>`` 命中 0 行而被拒绝。这是
    预期内的 fencing 行为（§20 G4），调用方应中止该陈旧执行而非重试。
    """


class IncompatibleCheckpointError(ValueError):
    """Resume 拒绝：checkpoint 的 graph_version 与当前 runtime 的 graph 版本不兼容。

    防止「v12 checkpoint 被 v13 graph 错误解释」（§20 G2）。
    """


class Checkpoint:
    """一次执行的中止点：已完成节点结果（keyed by node_id）+ 恢复契约版本信息（§20）。

    版本字段用于 resume 前的兼容性校验，防止「v12 checkpoint 被 v13 graph 解释」：
    - ``checkpoint_version``: checkpoint schema 自身演进版本（如 v1/v2）。
    - ``graph_id`` / ``graph_version``: 本 execution 当时基于的 ExecutionGraph 定义。
      resume 时须与当前 runtime 的 graph 版本兼容，否则拒绝恢复。
    - ``generation``: 与 execution_leases.generation 对齐的 fencing token；checkpoint
      写须携带，旧 owner 回写 0 rows 即被 fencing（FencedWriteError）。
    """

    def __init__(
        self,
        execution_id: str,
        completed: dict[str, Any] | None = None,
        updated_at: float | None = None,
        resumable: bool = False,
        *,
        checkpoint_version: int = 1,
        graph_id: str | None = None,
        graph_version: str | None = None,
        generation: int = 0,
    ) -> None:
        self.execution_id = execution_id
        self.completed = completed or {}
        self.updated_at = updated_at or time.monotonic()
        # stale 回收后置 True：所有权已释放，ExecutionGraph 的 resume 路径可基于本
        # checkpoint 继续未完成任务（默认 False = 正常推进中的 checkpoint）。
        self.resumable = resumable
        self.checkpoint_version = checkpoint_version
        self.graph_id = graph_id
        self.graph_version = graph_version
        self.generation = generation

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "completed": self.completed,
            "updated_at": self.updated_at,
            "resumable": self.resumable,
            "checkpoint_version": self.checkpoint_version,
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "generation": self.generation,
        }


class CheckpointStore(abc.ABC):
    """Checkpoint 持久化契约。"""

    @abc.abstractmethod
    async def load(self, execution_id: str) -> "Checkpoint | None":
        """读取指定执行的 checkpoint（不存在返回 None）。"""

    @abc.abstractmethod
    async def save(self, checkpoint: Checkpoint) -> None:
        """保存（或覆盖）一次执行的 checkpoint。"""


class InMemoryCheckpointStore(CheckpointStore):
    """进程内 checkpoint 存储（测试 / 单进程部署默认后端）。"""

    def __init__(self) -> None:
        self._store: dict[str, Checkpoint] = {}

    async def load(self, execution_id: str) -> "Checkpoint | None":
        return self._store.get(execution_id)

    async def save(self, checkpoint: Checkpoint) -> None:
        self._store[checkpoint.execution_id] = checkpoint


def new_execution_id() -> str:
    """生成新的 execution_id（供首次运行使用）。"""
    return uuid.uuid4().hex


class IdempotencyStore(abc.ABC):
    """幂等键存储契约（§9.2 Durability：idempotency）。

    同一 ``idempotency_key`` 的重复请求（如网络重试 / 客户端重复提交）应直接返回
    首次结果，而非重复执行。多副本场景应注入共享后端（如 PG / Redis）。
    """

    @abc.abstractmethod
    async def get(self, key: str) -> "Any | None":
        """命中返回缓存结果，未命中返回 None。"""

    @abc.abstractmethod
    async def save(self, key: str, result: Any) -> None:
        """缓存一次执行结果。"""


class InMemoryIdempotencyStore(IdempotencyStore):
    """进程内幂等存储（测试 / 单进程默认后端）。"""

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    async def get(self, key: str) -> "Any | None":
        return self._store.get(key)

    async def save(self, key: str, result: Any) -> None:
        self._store[key] = result


async def with_idempotency(key: str, store: IdempotencyStore, fn) -> Any:
    """幂等包裹：命中缓存直接返回，否则执行 ``fn`` 并缓存结果。

    ``fn`` 为 ``async () -> Any``。仅缓存成功结果；执行抛错不污染缓存
    （保证重试可重新进入逻辑）。
    """
    cached = await store.get(key)
    if cached is not None:
        return cached
    result = await fn()
    await store.save(key, result)
    return result


class ExecutionOwnershipStore(abc.ABC):
    """执行所有权 / 租约存储契约（§11 Durability：execution ownership / stale recovery）。

    单实例可用 ``asyncio.Lock``（已落地）；多副本需 distributed lease（见架构文档 §20）。
    本契约定义「谁在跑、租约何时到期、第几代」的抽象，供 stale recovery 检测与跨副本
    ownership 复用。

    §20 fencing：每次 ownership acquisition（acquire / claim）须递增 ``generation``
    并返回新 token；状态写操作携带该 token，旧 owner 回写 0 rows 即被 fencing。
    """

    @abc.abstractmethod
    async def acquire(self, execution_id: str, owner: str, ttl_s: float) -> "tuple[bool, int]":
        """获取执行所有权（租约 ttl_s 秒）。

        返回 ``(granted, generation)``：granted 为 True 表示获得；generation 为本次
        获取的 fencing token（旧 owner 用过期 token 回写状态会被 fencing）。
        """

    @abc.abstractmethod
    async def heartbeat(self, execution_id: str, ttl_s: float) -> None:
        """续租：把租约到期时间顺延 ttl_s。"""

    @abc.abstractmethod
    async def release(self, execution_id: str, owner: str) -> None:
        """释放所有权（执行完成 / 被回收）。仅当 owner 一致时生效，防止误释放他人持有的租约。"""

    @abc.abstractmethod
    async def get_owner(self, execution_id: str) -> "str | None":
        """返回当前所有者；无 / 已过期返回 None。"""

    @abc.abstractmethod
    async def list_stale(self, now: float) -> "list[str]":
        """返回「租约已过期且仍持有」的执行（stale，应被回收 / 恢复）。"""

    @abc.abstractmethod
    async def claim_stale(
        self, owner: str, ttl_s: float, *, now: float | None = None
    ) -> "list[tuple[str, int]]":
        """原子认领全部 stale 执行（winner-take-all 分布式 fencing）。

        将过期的租约所有权转移到 ``owner``，并把 ``generation`` 自增 1。
        并发调用时仅第一个成功获取行锁的调用能修改（如 PG 的 ``FOR UPDATE SKIP LOCKED``），
        其余调用拿到空结果——天然保证同一 execution 只有一个 winner。

        返回 ``[(execution_id, generation), ...]``（仅本调用成功认领的）。

        注意：winner 自行负责后续 resume；**不广播** NOTIFY 让所有副本 resume（否则
        会重新引入多副本重复恢复，见架构 §20）。
        """


class InMemoryExecutionOwnershipStore(ExecutionOwnershipStore):
    """进程内执行所有权存储（测试 / 单进程默认后端）。

    ``_owners``：execution_id -> (owner, expires_at, generation)。
    """

    def __init__(self) -> None:
        self._owners: dict[str, tuple[str, float, int]] = {}

    async def acquire(self, execution_id: str, owner: str, ttl_s: float) -> "tuple[bool, int]":
        cur = self._owners.get(execution_id)
        now = time.monotonic()
        if cur is not None and cur[1] > now:
            return (False, cur[2])  # 仍被他人/自己持有且未过期
        gen = cur[2] + 1 if cur is not None else 1
        self._owners[execution_id] = (owner, now + ttl_s, gen)
        return (True, gen)

    async def heartbeat(self, execution_id: str, ttl_s: float) -> None:
        cur = self._owners.get(execution_id)
        if cur is None:
            return
        self._owners[execution_id] = (cur[0], time.monotonic() + ttl_s, cur[2])

    async def release(self, execution_id: str, owner: str) -> None:
        cur = self._owners.get(execution_id)
        if cur is not None and cur[0] == owner:
            self._owners.pop(execution_id, None)

    async def get_owner(self, execution_id: str) -> "str | None":
        cur = self._owners.get(execution_id)
        if cur is None:
            return None
        if cur[1] <= time.monotonic():
            self._owners.pop(execution_id, None)
            return None
        return cur[0]

    async def list_stale(self, now: float) -> "list[str]":
        # 已释放（不在表）或租约未过期都不算 stale；仅「仍在表且 expiry<=now」为 stale
        return [eid for eid, (_, exp, _) in self._owners.items() if exp <= now]

    async def claim_stale(
        self, owner: str, ttl_s: float, *, now: float | None = None
    ) -> "list[tuple[str, int]]":
        claimed: list[tuple[str, int]] = []
        now = now if now is not None else time.monotonic()
        for eid, (cur_owner, exp, gen) in list(self._owners.items()):
            if exp <= now:
                new_gen = gen + 1
                self._owners[eid] = (owner, now + ttl_s, new_gen)
                claimed.append((eid, new_gen))
        return claimed


async def reap_stale_executions(
    ownership: ExecutionOwnershipStore,
    checkpoint_store: "CheckpointStore | None" = None,
    *,
    now: float | None = None,
    on_stale=None,
) -> "list[str]":
    """回收 stale 执行（§11 stale execution recovery 的纯逻辑半程）。

    复用 ``claim_stale`` 原子认领 stale 所有权（单进程下即直接回收），使其
    checkpoint 可被后续同 execution_id resume 接管（ExecutionGraph 已有
    checkpoint/resume）；若提供 ``on_stale`` 回调（``async (execution_id) -> None``）
    可附加告警 / 调度恢复。

    注：跨进程「真正唤醒」另一个副本去 resume 属环境依赖（见架构文档 §20），本函数只完成
    进程内检测 + 所有权回收这一可单测的纯逻辑部分。§20 起认领改为 winner-take-all
    fencing（claim_stale），reap 只是其单进程特例。
    """
    now = now if now is not None else time.monotonic()
    # §20：reap 即「认领全部 stale」（单进程下 winner 必为本调用）
    claimed = await ownership.claim_stale("reaper", 300.0, now=now)
    reclaimed = [eid for eid, _ in claimed]
    for eid in reclaimed:
        if checkpoint_store is not None:
            cp = await checkpoint_store.load(eid)
            if cp is not None:
                # 释放所有权后，ExecutionGraph 的 resume 路径可基于该 checkpoint 继续
                cp.resumable = True
                cp.updated_at = now
                await checkpoint_store.save(cp)
        if on_stale is not None:
            await on_stale(eid)
    return reclaimed


__all__ = [
    "Checkpoint",
    "CheckpointStore",
    "InMemoryCheckpointStore",
    "new_execution_id",
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "with_idempotency",
    "ExecutionOwnershipStore",
    "InMemoryExecutionOwnershipStore",
    "reap_stale_executions",
]


