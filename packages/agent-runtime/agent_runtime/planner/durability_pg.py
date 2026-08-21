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
import os
import time
from typing import Any

from agent_runtime.planner.durability import (
    Checkpoint,
    CheckpointStore,
    ExecutionOwnershipStore,
    FencedWriteError,
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
    """PG checkpoint 存储：execution_checkpoints 表（§20 带 fencing + 版本契约）。

    字段：
    - execution_id PK
    - completed jsonb（已完成节点结果）
    - updated_at timestamptz
    - resumable bool（stale 回收后置 True，允许 resume 接管）
    - checkpoint_version / graph_id / graph_version（恢复契约版本，resume 前校验）
    - generation（fencing token，与 execution_leases 对齐；save 带 WHERE generation 防护）
    """

    def __init__(self, pool: Any, *, table: str = "execution_checkpoints") -> None:
        self._pool = pool
        self._table = table

    async def load(self, execution_id: str) -> Checkpoint | None:
        sql = (
            f"SELECT completed, updated_at, resumable, checkpoint_version, "
            f"       graph_id, graph_version, generation "
            f"FROM {self._table} WHERE execution_id = %s"
        )
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql, (execution_id,))
            row = await cur.fetchone()
        if row is None:
            return None
        completed, updated_at, resumable, cpv, gid, gver, gen = row
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
            checkpoint_version=cpv,
            graph_id=gid,
            graph_version=gver,
            generation=gen,
        )

    async def save(self, checkpoint: Checkpoint) -> None:
        """持久化 checkpoint；带 §20 fencing 防护。

        fencing 由 **lease 的 generation token** 驱动（而非 checkpoint 自维护的
        generation 列）：``checkpoint.generation`` 须来自当前 lease 的 fencing token
        （即 ``ownership_store.acquire/claim`` 返回的 generation，经 runtime 注入）。

        防护规则：``ON CONFLICT DO UPDATE ... WHERE execution_id IN (
        SELECT execution_id FROM execution_leases WHERE execution_id=? AND generation=?
        )``。旧 owner 用过期 token 写时，lease 的 generation 已被 reaper claim 递增，
        子查询命中 0 行 → UPDATE 0 行 → RETURNING NULL → 抛 ``FencedWriteError``（G4）。
        generation=0 表示首写（INSERT），不做防护（此时尚无 lease token 可比）。
        """
        sql = (
            f"INSERT INTO {self._table} "
            f"(execution_id, completed, updated_at, resumable, "
            f" checkpoint_version, graph_id, graph_version, generation) "
            f"VALUES (%s, %s, now(), %s, %s, %s, %s, %s) "
            f"ON CONFLICT (execution_id) DO UPDATE "
            f"SET completed = EXCLUDED.completed, updated_at = now(), "
            f"    resumable = EXCLUDED.resumable, "
            f"    checkpoint_version = EXCLUDED.checkpoint_version, "
            f"    graph_id = EXCLUDED.graph_id, "
            f"    graph_version = EXCLUDED.graph_version, "
            f"    generation = EXCLUDED.generation "
            f"WHERE EXCLUDED.generation = 0 "
            f"   OR {self._table}.execution_id IN ("
            f"  SELECT execution_id FROM execution_leases "
            f"  WHERE execution_leases.execution_id = EXCLUDED.execution_id "
            f"    AND execution_leases.generation = EXCLUDED.generation"
            f") "
            f"RETURNING execution_id"
        )
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                sql,
                (
                    checkpoint.execution_id,
                    _dumps(checkpoint.completed),
                    checkpoint.resumable,
                    checkpoint.checkpoint_version,
                    checkpoint.graph_id,
                    checkpoint.graph_version,
                    checkpoint.generation,
                ),
            )
            row = await cur.fetchone()
        if checkpoint.generation != 0 and row is None:
            raise FencedWriteError(
                f"checkpoint save fenced: execution_id={checkpoint.execution_id} "
                f"generation={checkpoint.generation} 已过期，owner 已被取代"
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
    """PG 执行所有权/租约存储：execution_leases 表（C1 CAS + §20 fencing）。

    字段：
    - execution_id PK
    - owner TEXT（持有者标识，如 "pid:uuid"）NOT NULL
    - expires_at timestamptz（租约到期，TTL 自动过期防死锁）
    - generation BIGINT（fencing token，每次 ownership acquisition 自增 1）

    §20 关键约束（修复原 owner=NULL 广播式 reap 的设计断裂）：
    - acquire / claim 均返回最新 generation（fencing token）。
    - claim_stale 用 ``FOR UPDATE SKIP LOCKED`` 单事务锁定 stale 行并 ``generation+1``，
      并发 reaper 只有抢到行锁的 winner 能修改，天然 winner-take-all（Test 4）。
    - **绝不把 owner 置 NULL**：NOT NULL 约束即 schema 层面强制；winner 自行 resume，
      不广播 NOTIFY 让所有副本 resume（否则重新引入多副本重复恢复）。
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

    async def acquire(self, execution_id: str, owner: str, ttl_s: float) -> "tuple[bool, int]":
        """CAS 抢占所有权：仅当无行/已过期/同 owner 时成功。

        返回 ``(granted, generation)``：granted 为 True 表示获得；generation 为本次
        获取的 fencing token（旧 owner 用过期 token 回写状态会被 fencing）。
        """
        sql = (
            f"INSERT INTO {self._table} (execution_id, owner, expires_at, generation) "
            "VALUES (%s, %s, now() + (%s || ' seconds')::interval, 1) "
            "ON CONFLICT (execution_id) DO UPDATE "
            "SET owner = EXCLUDED.owner, expires_at = EXCLUDED.expires_at, "
            "    generation = {table}.generation + 1 "
            "WHERE {table}.expires_at < now() OR {table}.owner = EXCLUDED.owner "
            "RETURNING execution_id, generation"
        ).format(table=self._table)
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql, (execution_id, owner, str(ttl_s)))
            row = await cur.fetchone()
        if row is None:
            # 冲突但 WHERE 不满足（被他人持有且未过期）：读取当前 generation 透出
            async with self._pool.connection() as conn:
                cur = await conn.execute(
                    f"SELECT generation FROM {self._table} WHERE execution_id = %s",
                    (execution_id,),
                )
                r = await cur.fetchone()
            return (False, r[0] if r else 0)
        return (True, row[1])

    async def heartbeat(self, execution_id: str, ttl_s: float) -> None:
        """续租：仅当 owner 一致时延长租约到期时间（防续租他人租约）。"""
        sql = (
            f"UPDATE {self._table} "
            "SET expires_at = now() + (%s || ' seconds')::interval "
            "WHERE execution_id = %s AND owner = %s "
            "RETURNING execution_id"
        )
        async with self._pool.connection() as conn:
            cur = await conn.execute(sql, (str(ttl_s), execution_id, str(os.getpid())))
            await cur.fetchone()

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

    async def claim_stale(
        self, owner: str, ttl_s: float, *, now: float | None = None
    ) -> "list[tuple[str, int]]":
        """原子认领全部 stale 执行（winner-take-all 分布式 fencing，§20）。

        单事务内：``SELECT … FOR UPDATE SKIP LOCKED`` 锁定 stale 行 → 对每个
        成功锁定的行 ``UPDATE SET owner=new, expires_at=now()+ttl, generation+1``。
        并发 reaper 中，未抢到行锁者 ``SKIP LOCKED`` 跳过，最终同一 execution 只有一个
        winner（RETURNING 出 (execution_id, new_generation)）。winner 自行 resume；
        不广播 NOTIFY（避免多副本重复恢复）。

        返回本调用成功认领的 ``[(execution_id, generation), ...]``。
        """
        now = now if now is not None else time.time()
        claimed: list[tuple[str, int]] = []
        sql_lock = (
            f"SELECT execution_id FROM {self._table} "
            "WHERE expires_at <= now() "
            "FOR UPDATE SKIP LOCKED"
        )
        sql_update = (
            f"UPDATE {self._table} "
            "SET owner = %s, expires_at = now() + (%s || ' seconds')::interval, "
            "    generation = generation + 1 "
            "WHERE execution_id = %s "
            "RETURNING execution_id, generation"
        )
        async with self._pool.connection() as conn:
            async with conn.transaction():
                cur = await conn.execute(sql_lock)
                rows = await cur.fetchall()
                for (eid,) in rows:
                    cur = await conn.execute(sql_update, (owner, str(ttl_s), eid))
                    r = await cur.fetchone()
                    if r is not None:
                        claimed.append((r[0], r[1]))
        return claimed

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