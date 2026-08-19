# -*- coding: utf-8 -*-
"""P1.3：checkpoint 定时清理（防内存/存储无限增长）。

后台 asyncio 任务按固定间隔清理过期的 LangGraph checkpoint：
- **MongoCheckpointer**：每个 ``(tenant_id, thread_id, checkpoint_ns)`` 分组保留最新
  ``keep_per_thread`` 个 checkpoint（按 ``checkpoint_id`` 排序），删除更旧的。
  说明：Mongo schema 无时间字段，故用「最新 N 条」而非按 created_at 滚动。
- **AsyncPostgresSaver**：执行等价于规划 1.3 的保留最新 N 条 SQL（Postgres 的
  checkpoint_id 为 uuid，按写入顺序排序）。
- **InMemorySaver**：无持久化，跳过。

清理在独立后台 task 中周期运行，服务关闭时由 lifespan 取消。
"""
from __future__ import annotations

import asyncio
import os

from agent_core.logging import get_logger

logger = get_logger(__name__)

# 默认保留每个 thread 最近 N 个 checkpoint；老的全部清理
_KEEP_PER_THREAD = int(os.getenv("CHECKPOINT_KEEP_PER_THREAD", "5"))
# 清理间隔（小时）
_INTERVAL_HOURS = float(os.getenv("CHECKPOINT_RETENTION_HOURS", "6"))


async def _clean_mongo(checkpointer, keep_per_thread: int) -> int:
    """清理 MongoCheckpointer，返回删除文档数。"""
    coll = getattr(checkpointer, "_coll", None)
    if coll is None:
        return 0

    # 按 (tenant_id, thread_id, checkpoint_ns) 分组，每组保留最新 keep_per_thread 条。
    # checkpoint_id 为 uuid.hex，字典序即写入序，sort(-1) 取最新。
    # 逐组游标方案（Python 侧分组，避免复杂聚合歧义）。
    def _collect_ids() -> list[str]:
        to_delete: list[str] = []
        # 先拿所有分组键
        groups = coll.aggregate([
            {
                "$group": {
                    "_id": {
                        "tenant_id": "$tenant_id",
                        "thread_id": "$thread_id",
                        "checkpoint_ns": "$checkpoint_ns",
                    }
                }
            }
        ])
        for g in groups:
            key = g["_id"]
            cursor = coll.find(
                {
                    "tenant_id": key["tenant_id"],
                    "thread_id": key["thread_id"],
                    "checkpoint_ns": key["checkpoint_ns"],
                }
            ).sort("checkpoint_id", -1)
            ids = [d["checkpoint_id"] for d in cursor]
            to_delete.extend(ids[keep_per_thread:])
        return to_delete

    # 在线程池执行阻塞式聚合
    loop = asyncio.get_event_loop()
    from concurrent.futures import ThreadPoolExecutor
    _exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ckpt-clean")
    old_ids = await loop.run_in_executor(_exec, _collect_ids)

    if not old_ids:
        return 0

    def _delete() -> int:
        res = coll.delete_many({"checkpoint_id": {"$in": old_ids}})
        return res.deleted_count

    deleted = await loop.run_in_executor(_exec, _delete)
    _exec.shutdown(wait=False)
    return deleted


async def _clean_postgres(checkpointer, keep_per_thread: int) -> int:
    """清理 AsyncPostgresSaver（sqlalchemy 异步 Engine）。

    复用规划 1.3 SQL：按 (thread_id, checkpoint_ns) 分组保留最新 N 条（按写入序）。
    """
    engine = getattr(checkpointer, "engine", None)
    if engine is None:
        return 0
    sql = f"""
        DELETE FROM checkpoints
        WHERE (thread_id, checkpoint_ns, checkpoint_id) IN (
            SELECT thread_id, checkpoint_ns, checkpoint_id
            FROM (
                SELECT thread_id, checkpoint_ns, checkpoint_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY thread_id, checkpoint_ns
                           ORDER BY checkpoint_id DESC
                       ) AS rn
                FROM checkpoints
            ) ranked
            WHERE rn > {int(keep_per_thread)}
        )
    """
    from sqlalchemy import text
    async with engine.begin() as conn:
        result = await conn.execute(text(sql))
        return result.rowcount if hasattr(result, "rowcount") else 0


async def clean_checkpoints(checkpointer, *, keep_per_thread: int | None = None) -> int:
    """对给定 checkpointer 执行一次清理，返回删除条目数。

    不支持的类型（InMemorySaver 等）安全跳过，返回 0。
    """
    if keep_per_thread is None:
        keep_per_thread = _KEEP_PER_THREAD
    if checkpointer is None:
        return 0
    cls_name = type(checkpointer).__name__
    try:
        if cls_name == "MongoCheckpointer":
            return await _clean_mongo(checkpointer, keep_per_thread)
        if "PostgresSaver" in cls_name:
            return await _clean_postgres(checkpointer, keep_per_thread)
        # InMemorySaver / 其他：无需持久化清理
        return 0
    except Exception as e:  # 清理失败不应影响主服务
        logger.warning("checkpoint 清理异常（已跳过）: %s", e)
        return 0


async def _cleanup_loop(checkpointer, interval_hours: float, keep_per_thread: int) -> None:
    interval = max(interval_hours, 0.1) * 3600.0
    while True:
        await asyncio.sleep(interval)
        try:
            deleted = await clean_checkpoints(checkpointer, keep_per_thread=keep_per_thread)
            if deleted:
                logger.info("checkpoint 定时清理完成，删除 %d 条", deleted)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("checkpoint 定时清理失败（下轮重试）: %s", e)


async def start_checkpoint_cleaner(
    checkpointer=None,
    *,
    interval_hours: float | None = None,
    keep_per_thread: int | None = None,
) -> asyncio.Task | None:
    """启动后台清理任务。

    无有效 checkpointer（如 InMemorySaver）时返回 None（无需清理）。
    """
    if checkpointer is None:
        return None
    if type(checkpointer).__name__ in ("InMemorySaver",):
        return None
    iv = _INTERVAL_HOURS if interval_hours is None else interval_hours
    kp = _KEEP_PER_THREAD if keep_per_thread is None else keep_per_thread
    logger.info("启动 checkpoint 定时清理：间隔 %.1fh，保留每组最新 %d 条", iv, kp)
    return asyncio.create_task(_cleanup_loop(checkpointer, iv, kp))


async def stop_checkpoint_cleaner(task: asyncio.Task | None) -> None:
    """取消并等待清理任务结束（lifespan 关闭时调用）。"""
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


__all__ = [
    "clean_checkpoints",
    "start_checkpoint_cleaner",
    "stop_checkpoint_cleaner",
]
