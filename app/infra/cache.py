"""语义缓存：按向量相似度命中历史答案（``BaseSemanticCache`` app 侧实现）。

遵循 ``agent_core.cache.BaseSemanticCache`` 协议语义（统计接口 ``get_stats`` /
``reset_stats`` 统一），但本后端为函数式 PG 实现，key 构造为
``question.strip().lower()``（与 deepagents 的 ``build_cache_key`` 要素不同，
因向量空间/租户模型不一致，**不跨后端共享缓存数据**，见 TB-4）。

修复已知缺陷模式：后台写入任务必须持有引用（模块级集合 + done 回调移除），
否则 asyncio.create_task 返回值可能被 GC 提前回收导致写入丢失。
"""

import asyncio
import logging

from agent_core.cache import CacheStats

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task] = set()
_stats = CacheStats()


def spawn_background(coro) -> asyncio.Task:
    """统一的后台任务派发入口：持有引用防 GC。"""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def pending_background_tasks() -> int:
    return len(_background_tasks)


async def cache_lookup(pool, embedding: list[float], threshold: float) -> str | None:
    """返回余弦距离小于 threshold 的缓存答案；未命中返回 None。"""
    if pool is None:
        _stats.record("miss")
        return None
    sql = (
        "SELECT answer, embedding <=> %s AS distance FROM semantic_cache "
        "ORDER BY embedding <=> %s LIMIT 1"
    )
    try:
        async with pool.connection() as conn:
            row = await conn.execute(sql, (embedding, embedding))
            rec = await row.fetchone()
        if rec and rec[1] is not None and rec[1] < threshold:
            _stats.record("l2_hit")
            return rec[0]
    except Exception:
        logger.exception("语义缓存查询失败，降级为未命中")
    _stats.record("miss")
    return None


def get_stats() -> dict[str, int | float]:
    """返回缓存命中率统计快照。"""
    return _stats.snapshot()


def reset_stats() -> None:
    """清空统计。"""
    _stats.reset()


async def _cache_write(pool, question: str, answer: str, embedding: list[float]) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO semantic_cache (cache_key, question, answer, embedding) "
            "VALUES (%s, %s, %s, %s)",
            (question.strip().lower(), question, answer, embedding),
        )


def cache_store(pool, question: str, answer: str, embedding: list[float]) -> None:
    """非阻塞写入；失败静默（缓存是优化不是正确性依赖）。"""
    if pool is None or not answer:
        return

    async def _guarded():
        try:
            await _cache_write(pool, question, answer, embedding)
        except Exception:
            logger.exception("语义缓存写入失败")

    spawn_background(_guarded())
