"""PostgreSQL 持久化后端（§20.1/20.2 环境依赖落地）。

提供三个 ABC 的 PG 实现：
- PgCheckpointStore      → execution_checkpoints
- PgIdempotencyStore     → idempotency_keys
- PgExecutionOwnershipStore → execution_leases

设计遵循 §20 生产级约束：
- C1 所有状态变更原子 CAS（INSERT … ON CONFLICT / UPDATE … WHERE … RETURNING）
- C2 PG = 事实源，LISTEN/NOTIFY 仅作唤醒，periodic reconcile 兜底
- C3 admission 另文实现（PgAdmissionController），此处仅三大核心 Store
- C4 生产模式 fail fast，不在此处处理（由上层装配时校验）
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from agent_runtime.planner.durability import (
    Checkpoint,
    CheckpointStore,
    ExecutionOwnershipStore,
    IdempotencyStore,
)

logger = logging.getLogger(__name__)


class _JsonEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        try:
            return super().default(o)
        except TypeError:
            return str(o)


def _dumps(obj: Any) -> str:
    return json.dumps(obj, cls=_JsonEncoder, ensure_ascii=False)


def _loads(val: Any) -> Any:
    if isinstance(val, str):
        return json.loads(val)
    return val


class PgCheckpointStore(CheckpointStore):
    """PG checkpoint 存储：execution_checkpoints 表。

    字段：
    - execution_id PK
    - completed jsonb（已完成节点结果）
    - updated_at timestamptz
    - resumable bool（stale 回收后置 True，允许 resume 接管）
    """

    def __init__(self, pool: Any, *, table: str = "execution_checkpoints") -> None:
        self._pool = pool
        self._table = table

    async def load(self, execution_id: str) -> Checkpoint | None:
        sql = (
            f"SELECT completed, updated_at, resumable FROM {self._table} "
            "WHERE execution_id = %s"
        )
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql, (execution_id,))
            row = await cur.fetchone()
        if row is None:
            return None
        completed, updated_at, resumable = row
        # updated_at from PG is datetime; from fake pool may be float
        if isinstance(updated_at, (int, float)):
            updated_at_ts = updated_at
        else:
            updated_at_ts = updated_at.timestamp()
        return Checkpoint(
            execution_id=execution_id,
            completed=_loads(completed) if completed is not None else {},
            updated_at=updated_at_ts,
            resumable=bool(resumable),
        )

    async def save(self, checkpoint: Checkpoint) -> None:
        sql = (
            f"INSERT INTO {self._table} (execution_id, completed, updated_at, resumable) "
            "VALUES (%s, %s, now(), %s) "
            "ON CONFLICT (execution_id) DO UPDATE "
            "SET completed = EXCLUDED.completed, updated_at = now(), resumable = EXCLUDED.resumable"
        )
        async with self._pool.connection() as conn:
            await conn.execute(
                sql,
                (checkpoint.execution_id, _dumps(checkpoint.completed), checkpoint.resumable),
            )


class PgIdempotencyStore(IdempotencyStore):
    """PG 幂等存储：idempotency_keys 表。

    字段：
    - key PK
    - result jsonb
    - created_at timestamptz
    """

    def __init__(self, pool: Any, *, table: str = "idempotency_keys") -> None:
        self._pool = pool
        self._table = table

    async def get(self, key: str) -> Any | None:
        sql = f"SELECT result FROM {self._table} WHERE key = %s"
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql, (key,))
            row = await cur.fetchone()
        if row is None:
            return None
        return _loads(row[0])

    async def save(self, key: str, result: Any) -> None:
        sql = (
            f"INSERT INTO {self._table} (key, result) "
            "VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET result = EXCLUDED.result"
        )
        async with self._pool.connection() as conn:
            await conn.execute(sql, (key, _dumps(result)))


class PgExecutionOwnershipStore(ExecutionOwnershipStore):
    """PG 执行所有权/租约存储：execution_leases 表（C1 CAS 语义）。

    字段：
    - execution_id PK
    - owner TEXT（持有者标识，如 "pid:uuid"）
    - expires_at timestamptz（租约到期，TTL 自动过期防死锁）

    关键操作均为单条 SQL 原子 CAS：
    - acquire: INSERT … ON CONFLICT DO UPDATE WHERE (expires_at<now() OR owner=me) RETURNING
    - heartbeat: UPDATE … WHERE owner=me RETURNING
    - release: DELETE … WHERE owner=me
    - get_owner: SELECT owner WHERE expires_at>now()
    - list_stale: SELECT execution_id WHERE expires_at<=now()
    - reap_stale_notifying: UPDATE … SET owner=NULL, expires_at=NULL WHERE expires_at<now() RETURNING + NOTIFY
    """

    def __init__(
        self,
        pool: Any,
        *,
        table: str = "execution_leases",
        notify_channel: str = "execution_resumable",
    ) -> None:
        self._pool = pool
        self._table = table
        self._notify_channel = notify_channel

    async def acquire(self, execution_id: str, owner: str, ttl_s: float) -> bool:
        """CAS 抢占所有权：仅当无行/已过期/同 owner 时成功。

        返回 True 表示获得所有权；False 表示被他人持有且未过期。
        """
        sql = (
            f"INSERT INTO {self._table} (execution_id, owner, expires_at) "
            "VALUES (%s, %s, now() + (%s || ' seconds')::interval) "
            "ON CONFLICT (execution_id) DO UPDATE "
            "SET owner = EXCLUDED.owner, expires_at = EXCLUDED.expires_at "
            "WHERE {table}.expires_at < now() OR {table}.owner = EXCLUDED.owner "
            "RETURNING execution_id"
        ).format(table=self._table)
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql, (execution_id, owner, str(ttl_s)))
            row = await cur.fetchone()
        return row is not None

    async def heartbeat(self, execution_id: str, ttl_s: float, owner: str | None = None) -> bool:
        """续租：延长租约到期时间；当 owner 已被取代时返回 False（split-brain 的 A 侧感知）。

        §HA：原实现 ``WHERE execution_id=%s`` 无条件续租——新 owner 接管后旧 owner 仍能
        续租，导致「A 网络隔离 → B 接管 → A 仍续租成功」的假活跃。改为 ``WHERE owner=%s``
        校验：仅当租约仍由本 owner 持有时才顺延，否则返回 False 供心跳协程中止执行循环。

        返回 True=续租成功（仍持有）；False=租约已丢失（被接管/过期），调用方应停止执行。
        ``owner=None`` 时退化为仅按 execution_id 续租（测试/兼容场景，不校验），返回 True。
        """
        if owner is None:
            sql = (
                f"UPDATE {self._table} "
                "SET expires_at = now() + (%s || ' seconds')::interval "
                "WHERE execution_id = %s "
                "RETURNING execution_id"
            )
            async with self._pool.connection() as conn:
                cur = await conn.execute(sql, (str(ttl_s), execution_id))
                return (await cur.fetchone()) is not None
        sql = (
            f"UPDATE {self._table} "
            "SET expires_at = now() + (%s || ' seconds')::interval "
            "WHERE execution_id = %s AND owner = %s "
            "RETURNING execution_id"
        )
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql, (str(ttl_s), execution_id, owner))
            return (await cur.fetchone()) is not None

    async def release(self, execution_id: str, owner: str) -> None:
        """释放所有权：仅当 owner 一致时删除。"""
        sql = f"DELETE FROM {self._table} WHERE execution_id = %s AND owner = %s"
        async with self._pool.connection() as conn:
            await conn.execute(sql, (execution_id, owner))

    async def get_owner(self, execution_id: str) -> str | None:
        """返回当前 owner（租约未过期）；无/过期返回 None。"""
        sql = (
            f"SELECT owner FROM {self._table} "
            "WHERE execution_id = %s AND expires_at > now()"
        )
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql, (execution_id,))
            row = await cur.fetchone()
        return row[0] if row else None

    async def list_stale(self, now: float) -> list[str]:
        """返回租约已过期的 execution_id 列表。"""
        sql = f"SELECT execution_id FROM {self._table} WHERE expires_at <= now()"
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql)
            rows = await cur.fetchall()
        return [r[0] for r in rows]

    # ---- §20.1 跨进程 stale reaper + NOTIFY ----

    async def reap_stale_notifying(
        self,
        checkpoint_store: CheckpointStore | None = None,
        *,
        now: float | None = None,
        on_stale=None,
    ) -> list[str]:
        """原子回收 stale 执行并发 NOTIFY 唤醒其它副本（C1 + C2）。

        - 仅 UPDATE … WHERE expires_at<now() RETURNING 成功的行才算回收成功（防重复 resume）。
        - 回收后将对应 checkpoint 标记 resumable=True（供 resume 接管）。
        - 发送 NOTIFY execution_resumable 唤醒其它副本的 resume loop（C2 信号）。
        - 即使 NOTIFY 丢失，periodic reconcile 会再次调用此方法兜底。
        """
        now = now if now is not None else time.time()
        reclaimed: list[str] = []

        sql_reap = (
            f"UPDATE {self._table} "
            "SET owner = NULL, expires_at = NULL "
            "WHERE expires_at <= now() "
            "RETURNING execution_id"
        )
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql_reap)
            rows = await cur.fetchall()
        reclaimed = [r[0] for r in rows]

        for eid in reclaimed:
            if checkpoint_store is not None:
                cp = await checkpoint_store.load(eid)
                if cp is not None:
                    cp.resumable = True
                    cp.updated_at = now
                    await checkpoint_store.save(cp)
            if on_stale is not None:
                await on_stale(eid)

        if reclaimed:
            # 发送唤醒信号（C2：仅信号，不保证送达，periodic reconcile 兜底）
            try:
                async with self._pool.connection() as conn:
                    await conn.execute(f"NOTIFY {self._notify_channel}")
            except Exception:
                logger.warning("NOTIFY %s 发送失败", self._notify_channel, exc_info=True)

        return reclaimed

    # ---- §20.1 跨进程 resume 监听器（可选，供副本主动监听） ----

    async def listen_resumable(self, handler, *, stop_event: asyncio.Event | None = None) -> None:
        """长连接监听 execution_resumable NOTIFY，收到时调用 handler()。

        用法：副本启动时创建任务运行此方法；handler 内部应重新扫描 PG 找可恢复 execution。
        stop_event 用于优雅关闭（如 lifespan shutdown）。
        """
        sql_listen = f"LISTEN {self._notify_channel}"
        async with self._pool.connection() as conn:
            await conn.execute(sql_listen)
            logger.info("开始监听 %s", self._notify_channel)
            while True:
                if stop_event is not None and stop_event.is_set():
                    break
                try:
                    # psycopg v3: conn.notifies() 是 async generator
                    async for notify in conn.notifies():
                        if notify.channel == self._notify_channel:
                            await handler()
                        if stop_event is not None and stop_event.is_set():
                            break
                except asyncio.CancelledError:
                    break
                except Exception:
                    logger.warning("LISTEN %s 异常，重连中", self._notify_channel, exc_info=True)
                    await asyncio.sleep(1)
                    try:
                        await conn.execute(sql_listen)
                    except Exception:
                        await asyncio.sleep(5)


# ---- 便捷：基于 PG Store 的 reap_stale 封装 ----

async def pg_reap_stale(
    ownership: PgExecutionOwnershipStore,
    checkpoint_store: CheckpointStore | None = None,
    *,
    now: float | None = None,
    on_stale=None,
) -> list[str]:
    """在 PG 所有权后端上执行 stale 回收（含 NOTIFY）。

    这是 `reap_stale_executions` 的 PG 增强版，供 lifespan/定时任务调用。
    """
    return await ownership.reap_stale_notifying(
        checkpoint_store=checkpoint_store,
        now=now,
        on_stale=on_stale,
    )