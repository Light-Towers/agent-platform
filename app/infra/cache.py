"""语义缓存：按向量相似度命中历史答案（``BaseSemanticCache`` app 侧实现）。

遵循 ``agent_core.cache.BaseSemanticCache`` 协议语义（统计接口 ``get_stats`` /
``reset_stats`` 统一），key 构造现已复用内核 ``build_cache_key`` 单一真相
（TB-4 闭环：与 deepagents 共用同一 hash 逻辑，避免各写一份漂移）。

注意：本后端为函数式 PG 实现，lookup 端仅依赖 embedding 向量距离命中，
**不使用 cache_key 列参与命中**（key 仅作写入落库元数据）。因向量空间/
租户模型不一致，**不跨后端共享缓存数据**，见 TB-4 / S-5④ 范围外声明。

修复已知缺陷模式：后台写入任务必须持有引用（模块级集合 + done 回调移除），
否则 asyncio.create_task 返回值可能被 GC 提前回收导致写入丢失。
"""

import asyncio
import logging

from agent_core.cache import CacheStats, build_cache_key

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
    """返回余弦距离小于 threshold 的缓存答案；未命中返回 None。

    纯向量相似度命中，不参与 cache_key 匹配——故改用 build_cache_key 仅影响
    写入落库 metadata，不影响命中逻辑。
    """
    if pool is None:
        _stats.record("miss")
        return None
    sql = (
        "SELECT answer, embedding <=> %s::vector AS distance FROM semantic_cache "
        "ORDER BY embedding <=> %s::vector LIMIT 1"
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
    # cache_key 复用内核 build_cache_key 单一真相（intent/kb/tenant 在 app 侧缺省，
    # 退化为 sha256(""|query|{}|""|0.0)，与 deepagents 同款 hash 逻辑对齐）。
    cache_key = build_cache_key(intent="", rewritten_query=question.strip().lower())
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO semantic_cache (cache_key, question, answer, embedding) "
            "VALUES (%s, %s, %s, %s)",
            (cache_key, question, answer, embedding),
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
