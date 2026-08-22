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


class ExecutionNotOwned(RuntimeError):
    """§HA（C1 fail-closed）：执行所有权获取失败（acquire 返回 False）。

    意味着该 execution_id 的 lease 当前被其他副本持有，或未过期。调用方必须
    立即停止，不得继续执行任何 Skill——否则破坏 single-active-owner 不变量。
    """


class FencedWriteError(RuntimeError):
    """§HA（C3 stale writer fencing）：checkpoint 写入被拒绝。

    旧 owner（zombie/stale writer）尝试用较小/相等的 version 覆盖新 owner 的
    checkpoint，或写入者已不再持有 lease 时触发。数据保持不变（不被降级覆盖）。
    """


class Checkpoint:
    """一次执行的中止点：已完成节点结果（keyed by node_id）。"""

    def __init__(
        self,
        execution_id: str,
        completed: dict[str, Any] | None = None,
        updated_at: float | None = None,
        resumable: bool = False,
    ) -> None:
        self.execution_id = execution_id
        self.completed = completed or {}
        self.updated_at = updated_at or time.monotonic()
        # stale 回收后置 True：所有权已释放，ExecutionGraph 的 resume 路径可基于本
        # checkpoint 继续未完成任务（默认 False = 正常推进中的 checkpoint）。
        self.resumable = resumable

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "completed": self.completed,
            "updated_at": self.updated_at,
            "resumable": self.resumable,
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

    单实例可用 ``asyncio.Lock``（已落地）；多副本需 distributed lease（见架构文档 §17
    环境依赖 backlog）。本契约定义「谁在跑、租约何时到期」的抽象，供 stale recovery
    检测与跨副本ownership 复用。
    """

    @abc.abstractmethod
    async def acquire(self, execution_id: str, owner: str, ttl_s: float) -> bool:
        """获取执行所有权（租约 ttl_s 秒）。已持有且未过期则拒绝（返回 False）。"""

    @abc.abstractmethod
    async def heartbeat(self, execution_id: str, ttl_s: float, owner: str | None = None) -> bool:
        """续租：把租约到期时间顺延 ttl_s。

        §HA：返回 bool 表示「本次续租是否成功」。传 ``owner`` 时实现应校验租约仍由
        ``owner`` 持有；被其他副本接管后（split-brain 的 A 侧）应返回 False，供心跳
        协程感知所有权丢失并中止执行循环，避免旧 owner 继续产生副作用。
        """

    @abc.abstractmethod
    async def release(self, execution_id: str, owner: str) -> None:
        """释放所有权（执行完成 / 被回收）。仅当 owner 一致时生效，防止误释放他人持有的租约。"""

    @abc.abstractmethod
    async def get_owner(self, execution_id: str) -> "str | None":
        """返回当前所有者；无 / 已过期返回 None。"""

    @abc.abstractmethod
    async def list_stale(self, now: float) -> "list[str]":
        """返回「租约已过期且仍持有」的执行（stale，应被回收 / 恢复）。"""


class InMemoryExecutionOwnershipStore(ExecutionOwnershipStore):
    """进程内执行所有权存储（测试 / 单进程默认后端）。

    ``_owners``：execution_id -> (owner, expires_at)。
    """

    def __init__(self) -> None:
        self._owners: dict[str, tuple[str, float]] = {}

    async def acquire(self, execution_id: str, owner: str, ttl_s: float) -> bool:
        cur = self._owners.get(execution_id)
        now = time.monotonic()
        if cur is not None and cur[1] > now:
            return False  # 仍被他人/自己持有且未过期
        self._owners[execution_id] = (owner, now + ttl_s)
        return True

    async def heartbeat(self, execution_id: str, ttl_s: float, owner: str | None = None) -> bool:
        cur = self._owners.get(execution_id)
        if cur is None:
            return False
        if owner is not None and cur[0] != owner:
            # §HA：租约已被其他 owner 接管，旧 owner 感知所有权丢失 → 返回 False
            return False
        self._owners[execution_id] = (cur[0], time.monotonic() + ttl_s)
        return True

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
        return [eid for eid, (_, exp) in self._owners.items() if exp <= now]


async def reap_stale_executions(
    ownership: ExecutionOwnershipStore,
    checkpoint_store: "CheckpointStore | None" = None,
    *,
    now: float | None = None,
    on_stale=None,
) -> "list[str]":
    """回收 stale 执行（§11 stale execution recovery 的纯逻辑半程）。

    检测租约超时且仍持有所有权的执行：释放所有权，使其 checkpoint 可被后续
    同 execution_id resume 接管（ExecutionGraph 已有 checkpoint/resume）；
    若提供 ``on_stale`` 回调（``async (execution_id) -> None``）可附加告警 / 调度恢复。

    注：跨进程「真正唤醒」另一个副本去 resume 属环境依赖（见架构文档 §17），本函数只完成
    进程内检测 + 所有权回收这一可单测的纯逻辑部分。
    """
    now = now if now is not None else time.monotonic()
    stale = await ownership.list_stale(now)
    reclaimed: list[str] = []
    for eid in stale:
        # §HA：stale 回收须真正释放所有权（否则 B 无法接管）。
        # 租约已过期、owner 已失效，先取当前 owner 再精确释放（InMemory 的 release
        # 要求 owner 匹配；PG 路径走 reap_stale_notifying，不经过本函数）。
        cur_owner = await ownership.get_owner(eid)
        if cur_owner is not None:
            await ownership.release(eid, owner=cur_owner)
        if checkpoint_store is not None:
            cp = await checkpoint_store.load(eid)
            if cp is not None:
                # 释放所有权后，ExecutionGraph 的 resume 路径可基于该 checkpoint 继续
                cp.resumable = True
                cp.updated_at = now
                await checkpoint_store.save(cp)
        reclaimed.append(eid)
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


