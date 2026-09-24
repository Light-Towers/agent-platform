"""PostgreSQL + pgvector 连接池与 schema 迁移。

设计要点（吸取 deepagents 评审教训）：
- 懒加载必须加锁 + lifespan 预热，避免竞态；
- Schema 管理统一委托 agent_runtime.migrations.runner（P1-4 轻量版迁移系统）。
- 建表/ALTER 均由 migrations/*.up.sql 执行，本文件不包含 DDL 常量。

红线（lint_architecture R007）：禁止在本文件内联 CREATE TABLE / ALTER TABLE ADD COLUMN。
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

_pool = None
_pool_lock = asyncio.Lock()
_closing = False  # 关闭进行中标记，防止关闭途中被重新拉起成双池


async def init_pool(
    database_url: str = "",
    db_pool_max_size: int = 20,
    vector_dim: int | None = None,
):
    """lifespan 中调用一次；带锁防竞态。DATABASE_URL 未配置时返回 None（内存模式）。

    配置依赖倒置（Plan-F）：agent-runtime 不依赖 app.config，连接参数由调用方
    （app lifespan / scripts）从自身 Settings 注入；database_url 为空即内存模式。

    vector_dim: 向量维度。未提供时从 agent_core.memory.embedder.get_embedder().dim
    自动派生（单一事实源）。仅当 embedder 不可用时才回退到默认 512。
    """
    global _pool
    if not database_url:
        logger.info("DATABASE_URL 未配置，以内存模式运行（无持久化）")
        return None
    async with _pool_lock:
        if _closing:
            logger.warning("连接池正在关闭，跳过初始化")
            return None
        if _pool is not None:
            return _pool
        from pgvector.psycopg import register_vector_async
        from psycopg_pool import AsyncConnectionPool

        # 顺序约束：register_vector_async 在每个连接建立时即 fetch 'vector' 类型，
        # 故必须在打开连接池（建立首批连接）之前先启用 pgvector 扩展，
        # 否则报 "vector type not found in the database"（TB-7 真端到端暴露）。
        await ensure_extensions(database_url)

        pool = AsyncConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=db_pool_max_size,  # 可配置，默认 20，避免高并发池耗尽
            kwargs={"autocommit": True},
            # 必须用 register_vector_async：AsyncConnectionPool 的连接是 AsyncConnection，
            # 同步版 register_vector 调用 TypeInfo.fetch 会返回未 await 的 coroutine，
            # 导致 'coroutine' object has no attribute 'register'（TB-7 真端到端暴露）。
            configure=register_vector_async,
            open=False,
        )
        await pool.open(wait=True)
        await ensure_schema(pool, vector_dim=vector_dim)
        _pool = pool
        logger.info("PostgreSQL 连接池就绪，schema 已校验")
        return _pool


async def ensure_extensions(database_url: str) -> None:
    """连接池建立前，用一次性连接启用 pgvector 扩展（幂等）。"""
    from psycopg import AsyncConnection

    async with await AsyncConnection.connect(database_url, autocommit=True) as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")


async def ensure_schema(pool, vector_dim: int | None = None) -> None:
    """委托迁移 runner 执行 schema 管理（P1-4 轻量版）。

    原逻辑（CREATE IF NOT EXISTS 大模板 + ALTER try/except: pass）已重构为：
    - migrations/001_baseline.up.sql：全量建表
    - migrations/002_*.up.sql / 003_*.up.sql：增量 ALTER
    - runner：advisory_xact_lock + 事务 + 版本追踪 + 模板替换

    vector_dim 参数保留以兼容现有调用方（init_pool 传入），
    runner 内部统一从 embedder 解析维度并替换 SQL 模板。
    """
    from agent_runtime.migrations.runner import run_migrations

    applied = await run_migrations(pool)
    if applied:
        logger.info(
            "ensure_schema: %d migration(s) applied, now at version %d",
            len(applied),
            applied[-1].version,
        )
    else:
        logger.debug("ensure_schema: schema already up-to-date")


def get_pool():
    """已初始化则返回连接池，否则 None。不做隐式初始化（初始化只发生在 lifespan）。"""
    return _pool


async def close_pool() -> None:
    """优雅关闭连接池（多副本 SIGTERM → lifespan shutdown 路径）。

    设计要点（消除关闭竞态）：
    - 先置 ``_closing`` 并在锁内将全局 ``_pool`` 摘掉（置 None），使新请求
      ``get_pool()`` 立即返回 None（优雅降级），不会从「关闭中」的池借用连接。
    - 退出锁后再 ``await pool.close(timeout=30)``：优雅等待在途连接归还，
      timeout 为等待上限，**不等于强关、不取消在途请求**；达到上限后允许
      关闭流程继续，不阻塞进程退出。
    - ``close()`` 自身异常被记录且 ``_closing`` 复位，绝不永久卡死 runtime。
    - 并发/重复调用安全（幂等）。
    """
    global _pool, _closing
    async with _pool_lock:
        if _pool is None or _closing:
            return
        _closing = True
        pool = _pool
        _pool = None  # 立即摘掉全局引用，避免新请求从关闭中池借用连接
    try:
        await pool.close(timeout=30)
    except Exception as e:
        logger.warning("连接池关闭异常（忽略，进程即将退出）: %s", e)
    finally:
        _closing = False


async def ping() -> bool:
    """健康检查用：连接池存活即认为存储可用。"""
    if _pool is None:
        return False
    try:
        async with _pool.connection() as conn:
            await conn.execute("SELECT 1")
        return True
    except Exception:
        return False


async def vector_search(
    pool,
    table: str,
    cols: str,
    embedding: list[float],
    k: int = 1,
    where: str = "embedding IS NOT NULL",
    where_params: tuple = (),
) -> list[tuple]:
    """pgvector 余弦距离向量检索（app 包内通用）。

    SQL: SELECT {cols} FROM {table} WHERE {where} ORDER BY embedding <=> %s LIMIT %s

    安全：table/cols 经标识符白名单校验（仅含 [a-z0-9_]，列名逗号分隔），
    拒绝任意字符串注入，避免误用导致的 SQL 注入式表名/列名。
    """
    import re

    _IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
    if not _IDENT.match(table or ""):
        raise ValueError(f"vector_search: 非法表名 {table!r}（仅允许 [a-z0-9_]）")
    for _col in cols.split(","):
        _col = _col.strip()
        if not _col or not _IDENT.match(_col):
            raise ValueError(f"vector_search: 非法列名 {cols!r}（仅允许 [a-z0-9_]，逗号分隔）")
    sql = (
        f"SELECT {cols} FROM {table} WHERE {where} "
        f"ORDER BY embedding <=> %s::vector LIMIT %s"
    )
    params = (*where_params, embedding, k)
    async with pool.connection() as conn:
        cur = await conn.execute(sql, params)
        return await cur.fetchall()
